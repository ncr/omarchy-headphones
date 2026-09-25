"""Restoration is tested independently of the Bluetooth transport."""
import unittest
from unittest.mock import Mock
from tools.tozo_probe import cycle


class Probe(unittest.TestCase):
    def test_full_queue_and_verified_restoration(self):
        driver=Mock();driver.read_mode.return_value='anc'
        driver.set_and_read.side_effect=lambda mode: mode
        cycle(driver,['off','anc','ambient','wind','leisure','adaptive'],Mock())
        self.assertEqual([c.args[0] for c in driver.set_and_read.call_args_list],
                         ['off','anc','ambient','wind','leisure','adaptive','anc'])

    def test_unknown_initial_state_aborts_all_writes(self):
        driver=Mock();driver.read_mode.return_value=None
        with self.assertRaises(RuntimeError):cycle(driver,['off','anc'],Mock())
        driver.set_and_read.assert_not_called()

    def test_interrupt_or_send_failure_restores_observed_initial_mode(self):
        for error in (KeyboardInterrupt(),RuntimeError('lost'),TimeoutError('reply')):
            driver=Mock();driver.read_mode.return_value='ambient'
            driver.set_and_read.side_effect=[error,'ambient']
            with self.assertRaises(type(error)):cycle(driver,['off','ambient'],Mock())
            self.assertEqual([c.args[0] for c in driver.set_and_read.call_args_list],['off','ambient'])

    def test_unconfirmed_restore_is_failure(self):
        driver=Mock();driver.read_mode.return_value='anc'
        driver.set_and_read.side_effect=['off','anc','ambient']
        report=Mock()
        with self.assertRaises(RuntimeError):cycle(driver,['off','anc'],report)
        self.assertTrue(any('RESTORATION FAILED' in c.args[0] for c in report.call_args_list))
