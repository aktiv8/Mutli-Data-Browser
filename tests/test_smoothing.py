import unittest

import numpy as np

import smoothing


class TestSavitzkyGolay(unittest.TestCase):
    def test_reproduces_polynomial_away_from_edges(self):
        x = np.arange(60, dtype=float)
        y = 0.5 * x ** 2 - 3 * x + 7
        window = 9
        out = smoothing.savitzky_golay(y, window, order=2)
        half = window // 2
        np.testing.assert_allclose(out[half:-half], y[half:-half], atol=1e-8)

    def test_preserves_length(self):
        y = np.random.default_rng(1).normal(size=37)
        out = smoothing.savitzky_golay(y, 11, order=2)
        self.assertEqual(len(out), len(y))

    def test_reduces_noise(self):
        rng = np.random.default_rng(0)
        x = np.linspace(0, 10, 300)
        signal = np.sin(x)
        noisy = signal + rng.normal(0, 0.3, size=x.size)
        out = smoothing.savitzky_golay(noisy, 15, order=3)
        err_raw = np.mean((noisy - signal) ** 2)
        err_smooth = np.mean((out - signal) ** 2)
        self.assertLess(err_smooth, err_raw * 0.5)

    def test_window_larger_than_data_does_not_crash(self):
        y = np.array([1.0, 2.0, 3.0, 2.0, 1.0])
        out = smoothing.savitzky_golay(y, 21, order=2)
        self.assertEqual(len(out), len(y))

    def test_too_short_returns_unchanged(self):
        y = np.array([1.0, 2.0])
        out = smoothing.savitzky_golay(y, 9, order=2)
        np.testing.assert_array_equal(out, y)


class TestFourierLowpass(unittest.TestCase):
    def test_constant_signal_unchanged(self):
        y = np.full(64, 3.7)
        out = smoothing.fourier_lowpass(y, cutoff=5)
        np.testing.assert_allclose(out, y, atol=1e-9)

    def test_preserves_length(self):
        y = np.random.default_rng(2).normal(size=101)
        out = smoothing.fourier_lowpass(y, cutoff=8)
        self.assertEqual(len(out), len(y))

    def test_attenuates_high_frequency_more_than_low(self):
        n = 256
        x = np.arange(n)
        low = np.sin(2 * np.pi * 2 * x / n)
        high = np.sin(2 * np.pi * 40 * x / n)
        out_low = smoothing.fourier_lowpass(low, cutoff=10)
        out_high = smoothing.fourier_lowpass(high, cutoff=10)
        self.assertGreater(np.std(out_low), 0.8 * np.std(low))
        self.assertLess(np.std(out_high), 0.3 * np.std(high))

    def test_too_short_returns_unchanged(self):
        y = np.array([1.0, 2.0, 3.0])
        out = smoothing.fourier_lowpass(y, cutoff=1)
        np.testing.assert_array_equal(out, y)


class TestGaussHermiteTransfer(unittest.TestCase):
    def test_unity_at_dc(self):
        tf = smoothing.gauss_hermite_transfer(50, nc=10)
        self.assertAlmostEqual(tf[0], 1.0, places=9)

    def test_half_power_at_nc(self):
        tf = smoothing.gauss_hermite_transfer(50, nc=10)
        self.assertAlmostEqual(tf[10], 0.5, places=6)

    def test_monotonically_decreasing(self):
        tf = smoothing.gauss_hermite_transfer(50, nc=10)
        self.assertTrue(np.all(np.diff(tf) <= 1e-12))


class TestGaussHermiteSmooth(unittest.TestCase):
    def test_preserves_length(self):
        y = np.random.default_rng(6).normal(size=80)
        out = smoothing.gauss_hermite_smooth(y, nc=8)
        self.assertEqual(len(out), len(y))

    def test_reduces_noise(self):
        rng = np.random.default_rng(7)
        x = np.linspace(0, 10, 200)
        signal = np.sin(x)
        noisy = signal + rng.normal(0, 0.3, size=x.size)
        out = smoothing.gauss_hermite_smooth(noisy, nc=6)
        err_raw = np.mean((noisy - signal) ** 2)
        err_smooth = np.mean((out - signal) ** 2)
        self.assertLess(err_smooth, err_raw * 0.5)

    def test_detrends_sloping_background(self):
        # a strong linear background plus noise: the line/parabola removal
        # should stop the ends running away the way a bare FFT low-pass can.
        rng = np.random.default_rng(8)
        x = np.linspace(0, 1, 150)
        trend = 40 * x
        noisy = trend + rng.normal(0, 0.5, size=x.size)
        out = smoothing.gauss_hermite_smooth(noisy, nc=10)
        self.assertLess(abs(out[0] - trend[0]), 5.0)
        self.assertLess(abs(out[-1] - trend[-1]), 5.0)

    def test_too_short_returns_unchanged(self):
        y = np.array([1.0, 2.0, 3.0])
        out = smoothing.gauss_hermite_smooth(y, nc=1)
        np.testing.assert_array_equal(out, y)


class TestAutoCutoff(unittest.TestCase):
    def test_finds_knee_between_signal_and_noise(self):
        rng = np.random.default_rng(3)
        n = 512
        x = np.arange(n)
        signal = 5 * np.sin(2 * np.pi * 3 * x / n)
        y = signal + rng.normal(0, 0.05, size=n)
        cutoff = smoothing.auto_cutoff(y)
        self.assertGreaterEqual(cutoff, 2)
        self.assertLessEqual(cutoff, n // 4)

    def test_short_input_does_not_crash(self):
        y = np.array([1.0, 2.0, 1.0, 2.0])
        cutoff = smoothing.auto_cutoff(y)
        self.assertGreaterEqual(cutoff, 1)


class TestSmoothDispatcher(unittest.TestCase):
    def test_none_returns_unchanged(self):
        y = np.array([1.0, 5.0, 2.0, 9.0, 3.0])
        out = smoothing.smooth(y, "None", 0.7)
        np.testing.assert_array_equal(out, y)

    def test_unknown_method_raises(self):
        with self.assertRaises(ValueError):
            smoothing.smooth(np.array([1.0, 2.0, 3.0]), "Boxcar")

    def test_savitzky_golay_strength_changes_window(self):
        rng = np.random.default_rng(4)
        y = np.sin(np.linspace(0, 6, 200)) + rng.normal(0, 0.2, 200)
        gentle = smoothing.smooth(y, "Savitzky-Golay", 0.0)
        strong = smoothing.smooth(y, "Savitzky-Golay", 1.0)
        self.assertEqual(len(gentle), len(y))
        self.assertEqual(len(strong), len(y))
        self.assertLess(np.std(np.diff(strong)), np.std(np.diff(gentle)))

    def test_fourier_strength_changes_cutoff(self):
        rng = np.random.default_rng(5)
        y = np.sin(np.linspace(0, 6, 200)) + rng.normal(0, 0.2, 200)
        gentle = smoothing.smooth(y, "Fourier low-pass", 0.0)
        strong = smoothing.smooth(y, "Fourier low-pass", 1.0)
        self.assertEqual(len(gentle), len(y))
        self.assertEqual(len(strong), len(y))
        self.assertLess(np.std(np.diff(strong)), np.std(np.diff(gentle)))

    def test_gauss_hermite_strength_changes_nc(self):
        rng = np.random.default_rng(9)
        y = np.sin(np.linspace(0, 6, 200)) + rng.normal(0, 0.2, 200)
        gentle = smoothing.smooth(y, "Gauss-Hermite Smooth", 0.0)
        strong = smoothing.smooth(y, "Gauss-Hermite Smooth", 1.0)
        self.assertEqual(len(gentle), len(y))
        self.assertEqual(len(strong), len(y))
        self.assertLess(np.std(np.diff(strong)), np.std(np.diff(gentle)))

    def test_short_input_returns_unchanged(self):
        y = np.array([1.0, 2.0])
        out = smoothing.smooth(y, "Savitzky-Golay", 0.5)
        np.testing.assert_array_equal(out, y)


if __name__ == "__main__":
    unittest.main()
