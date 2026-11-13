"""Tests for the in-Live test bridge itself, run in the simulated Live.

Run from the project folder: python3.11 -m unittest discover tests
"""
import json
import os
import socket
import sys
import threading
import types
import unittest
from unittest import mock

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, 'sim'))
sys.path.insert(0, os.path.join(HERE, 'live'))
import live_sim  # noqa: E402

PAD = 0x60


@unittest.skipUnless(live_sim.is_available(), 'needs Python 3.11 and Ableton Live 12')
class DevBridgeTest(unittest.TestCase):

    def setUp(self):
        self.sim = live_sim.LiveSim()  # installs the simulated `Live` module first
        import dev_bridge
        from Launchkey_MK3_Step import create_instance
        self.surface = self.sim.start_surface(create_instance)
        self.sim.take_sent()
        self.sim.answer_identity_requests = True  # like the real Launchkey
        self.bridge = dev_bridge.attach(self.surface, port=0)
        self.disconnected = False

    def tearDown(self):
        self.bridge.stop()
        if not self.disconnected:
            self.surface.disconnect()

    def to_hardware(self):
        return self.sim.take_sent()

    def ask(self, code):
        """Send code over the socket while ticking Live's display timer, like Live would."""
        reply = {}

        def client():
            with socket.create_connection(('127.0.0.1', self.bridge.port)) as connection:
                stream = connection.makefile('rw')
                stream.write(json.dumps({'code': code}) + '\n')
                stream.flush()
                reply.update(json.loads(stream.readline()))

        thread = threading.Thread(target=client)
        thread.start()
        while thread.is_alive():
            self.sim.pump(ticks=1)
            thread.join(0.01)
        return reply

    def test_lights_reach_the_launchkey_and_are_recorded(self):
        self.bridge.inject((0xBF, 3, 5))
        self.sim.pump(ticks=2)
        sent = self.to_hardware()
        self.assertIn((0xBF, 3, 2), sent)
        self.assertIn((0x90, PAD, 1), sent)  # the step grid lights up on the hardware
        self.assertIn((0x90, PAD, 1), self.bridge.sent)  # and is recorded for the test

    def test_disconnecting_frees_the_port_for_the_next_instance(self):
        # Found in Live: loading a set makes Live create the script again, and the new bridge
        # couldn't listen on the port the old one still held, so the script failed to load.
        port = self.bridge.port
        self.surface.disconnect()
        self.disconnected = True
        replacement = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            replacement.bind(('127.0.0.1', port))
        finally:
            replacement.close()

    def test_a_bridge_that_fails_never_stops_the_script_loading(self):
        import Launchkey_MK3_Step
        broken = types.ModuleType('Launchkey_MK3_Step.dev_bridge')
        broken.attach = mock.Mock(side_effect=OSError(48, 'Address already in use'))
        with mock.patch.dict(sys.modules, {'Launchkey_MK3_Step.dev_bridge': broken}):
            with self.assertLogs('Launchkey_MK3_Step', level='ERROR'):
                Launchkey_MK3_Step._attach_dev_bridge(self.surface)  # logged, not raised
        broken.attach.assert_called_once_with(self.surface)

    def test_code_runs_on_lives_thread_and_returns_a_result(self):
        self.bridge.inject((0xBF, 3, 5))
        reply = self.ask('result = [surface._is_step_mode_active(), len(song.tracks)]')
        self.assertEqual(reply, {'result': [True, 2]})
        self.assertIn('ZeroDivisionError', self.ask('result = 1 / 0')['error'])


if __name__ == '__main__':
    unittest.main()
