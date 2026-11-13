"""Test-only bridge that lets an outside test drive the control surface inside a running Live.

Only `./install.sh --dev-bridge` puts this file next to the script; a normal install removes it.

It listens on 127.0.0.1:PORT. Each request is one line of JSON, {"code": "..."}. The code runs on
Live's main thread (from update_display) with `surface`, `song`, `app`, `Live`, `bridge` and
`inject` in scope; the value it leaves in `result` comes back as one line of JSON.

While attached, everything the script sends to the Launchkey is recorded (bridge.sent), and so
is everything it receives (bridge.received, marked when injected by the test).
"""
import json
import logging
import queue
import socket
import threading
import traceback

import Live

logger = logging.getLogger(__name__)

PORT = 9890
REQUEST_TIMEOUT = 20.0


def attach(surface, port=PORT):
    bridge = DevBridge(surface)
    bridge.start(port)
    return bridge


class OutputRecorder:
    """Stands in for Live's c_instance: records what the script sends, then sends it."""

    def __init__(self, c_instance, bridge):
        self._c_instance = c_instance
        self._bridge = bridge

    def send_midi(self, midi_bytes):
        self._bridge.sent.append(tuple(midi_bytes))
        self._c_instance.send_midi(midi_bytes)

    def __getattr__(self, name):
        return getattr(self._c_instance, name)


class DevBridge:

    def __init__(self, surface):
        self.surface = surface
        self.sent = []
        self.received = []
        self._injecting = False
        self._requests = queue.Queue()
        self._server = None
        self._thread = None
        surface._c_instance = OutputRecorder(surface._c_instance, self)
        self._wrap_surface()

    # --- Hooks on the surface ---

    def _wrap_surface(self):
        surface = self.surface
        update_display = surface.update_display
        receive_midi = surface.receive_midi
        receive_midi_chunk = getattr(surface, 'receive_midi_chunk', None)
        disconnect = surface.disconnect

        def bridged_update_display():
            update_display()
            self._run_requests()

        def bridged_receive_midi(midi_bytes):
            self._incoming(midi_bytes)
            receive_midi(midi_bytes)

        def bridged_receive_midi_chunk(midi_chunk):
            for midi_bytes in midi_chunk:
                self._incoming(midi_bytes)
            receive_midi_chunk(midi_chunk)

        def bridged_disconnect():
            self.stop()  # free the port: Live creates the script again when a set loads
            disconnect()

        surface.update_display = bridged_update_display
        surface.disconnect = bridged_disconnect
        surface.receive_midi = bridged_receive_midi
        if receive_midi_chunk is not None:
            surface.receive_midi_chunk = bridged_receive_midi_chunk

    def _incoming(self, midi_bytes):
        self.received.append((tuple(midi_bytes), self._injecting))

    def inject(self, *messages):
        """Feed MIDI to the script as if the Launchkey had sent it."""
        for message in messages:
            self._injecting = True
            try:
                self.surface.receive_midi(tuple(message))
            finally:
                self._injecting = False

    # --- Server ---

    def start(self, port=PORT):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(('127.0.0.1', port))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, name='LaunchkeyDevBridge', daemon=True)
        self._thread.start()
        logger.info('Dev bridge listening on port %s', self.port)

    def stop(self):
        """Close the server."""
        server, self._server = self._server, None
        if server is not None:
            server.close()
        logger.info('Dev bridge stopped')

    def _serve(self):
        while self._server is not None:
            try:
                connection, _ = self._server.accept()
            except OSError:
                return
            with connection:
                stream = connection.makefile('rw')
                for line in stream:
                    reply = self._handle(line)
                    stream.write(json.dumps(reply, default=repr) + '\n')
                    stream.flush()

    def _handle(self, line):
        try:
            code = json.loads(line)['code']
        except (ValueError, KeyError):
            return {'error': 'bad request'}
        answer = queue.Queue()
        self._requests.put((code, answer))
        try:
            return answer.get(timeout=REQUEST_TIMEOUT)
        except queue.Empty:
            return {'error': 'timed out waiting for Live'}

    def _run_requests(self):
        while True:
            try:
                code, answer = self._requests.get_nowait()
            except queue.Empty:
                return
            scope = {
                'surface': self.surface, 'song': self.surface.song,
                'app': Live.Application.get_application(), 'Live': Live,
                'bridge': self, 'inject': self.inject, 'result': None}
            try:
                exec(code, scope)
                answer.put({'result': scope.get('result')})
            except Exception:
                answer.put({'error': traceback.format_exc()})
