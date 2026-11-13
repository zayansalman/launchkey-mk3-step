"""Launchkey MK3 Step: Ableton's Launchkey MK3 script plus a drum step sequencer."""
import logging

from Launchkey_MK3 import get_capabilities as get_stock_capabilities

from .launchkey_mk3_step import Launchkey_MK3_Step

logger = logging.getLogger(__name__)


def get_capabilities():
    return get_stock_capabilities()


def create_instance(c_instance):
    surface = Launchkey_MK3_Step(c_instance=c_instance)
    _attach_dev_bridge(surface)
    return surface


def _attach_dev_bridge(surface):
    """Hook for the in-Live tests; does nothing unless `install.sh --dev-bridge` added the bridge.

    Test-only code must never stop the script loading, so a failure here is only logged.
    """
    try:
        from . import dev_bridge
    except ImportError:
        return
    try:
        dev_bridge.attach(surface)
    except Exception:
        logger.exception('Dev bridge not attached')
