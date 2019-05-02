import numpy as np
from scipy import signal
import logging

LOGGER = logging.getLogger('timeflux.' + __name__)

def _get_com_factor(com, span, halflife, alpha):
    valid_count = sum(1 for _ in filter(None.__ne__, [com, span, halflife, alpha]))
    if valid_count > 1:
        raise ValueError("comass, span, halflife, and alpha "
                         "are mutually exclusive")
    # Convert to smoothing coefficient; domain checks ensure 0 < alpha <= 1
    if com is not None:
        if com < 0:
            raise ValueError("comass must satisfy: com >= 0")
        alpha = 1 / (1 + com)
    elif span is not None:
        if span < 1:
            raise ValueError("span must satisfy: span >= 1")
        alpha = 2 / (span + 1)
    elif halflife is not None:
        if halflife <= 0:
            raise ValueError("halflife must satisfy: halflife > 0")
        alpha = 1 - np.exp(np.log(0.5) / halflife)
    elif alpha is not None:
        if alpha <= 0 or alpha > 1:
            raise ValueError("alpha must satisfy: 0 < alpha <= 1")
    else:
        raise ValueError("Must pass one of com, span, halflife, or alpha")

    return float(alpha)

def _hz_to_nyq(freqs, nyq):
    if type(freqs)==list:
        return [freq/nyq for freq in freqs]
    else:
        return freqs/nyq

def _nyq_to_hz(freqs, nyq):
    if type(freqs)==list:
        return [freq*nyq for freq in freqs]
    else:
        return freqs*nyq


def design_edges(freqs, nyq, mode):
    """Design filter edges.

    Args:
        freqs (list): Transition frequencies in Hz.
        mode (str): Filter mode (`lowpass`, `highpass`, `bandstop` or `bandpass`).
        nyq: Nyquist frequency (half sampling rate).

    Returns:
        array: freqs. Updated frequencies with transition bands.
        array: gains.  Filter gain at frequency sampling points.
        list: wp.  Passband edge frequencies.
        list: ws. Stopband edge frequencies.

    **Filter edges design**

    The -6 dB point for all filters is in the middle of the transition band.

    If no transition band is given, default is to use:

        * ``l_trans_bandwidth`` =
          .. math::  min(max(l_{freq} * 0.25, 2), l_{freq})
        * ``h_trans_bandwidth`` =
          .. math:: min(max(h_{freq} * 0.25, 2.), fs / 2. - h_{freq})

    **Band-pass filter**

    The frequency response is (approximately) given by:

    .. image:: /../../timeflux_dsp/doc/static/image/edges_bandpass.svg

    ..
    ..
    ..   1-|               ----------
    ..     |             /|         | \
    .. \|H\| |            / |         |  \
    ..     |           /  |         |   \
    ..     |          /   |         |    \
    ..   0-|----------    |         |     --------------
    ..     |         |    |         |     |            |
    ..     0        Fs1  Fp1       Fp2   Fs2          Nyq


    Where:

        * l_trans_bandwidth  = Fp1 - Fs1 in Hz
        * Fh_trans_bandwidth = Fs2 - Fp2 +  in Hz
        * ``freqs`` = `[Fp1, Fs1, Fs2, Fp2]`


    **Band-stop filter**

    The frequency response is (approximately) given by:

    .. image:: /../../timeflux_dsp/doc/static/image/edges_bandstop.svg

    ..
    ..        1-|---------                   ----------
    ..          |         \                 /
    ..      \|H\| |          \               /
    ..          |           \             /
    ..          |            \           /
    ..        0-|             -----------
    ..          |        |    |         |    |        |
    ..          0       Fp1  Fs1       Fs2  Fp2      Nyq


    Where:

        * l_trans_bandwidth  = Fs1 - Fp1 in Hz
        * Fh_trans_bandwidth = Fp2 - Fs2 +  in Hz
        * ``freqs`` = `[Fp1, Fs1, Fs2, Fp2]`




    **Low-pass filter**

        The frequency response is (approximately) given by:

        .. image:: /../../timeflux_dsp/doc/static/image/edges_lowpass.svg


    ..    1-|------------------------
    ..      |                        \
    ..  \|H\| |                         \
    ..      |                          \
    ..      |                           \
    ..    0-|                            ----------------
    ..      |                       |    |              |
    ..      0                      Fp  Fstop           Nyq

    Where :

        * h_trans_bandwidth = Fstop - Fp in Hz
        * ``freqs`` = `[Fp, Fstop]`

    **High-pass filter**

        The frequency response is (approximately) given by:

    .. image:: /../../timeflux_dsp/doc/static/image/edges_highpass.svg


    ..
    ..    1-|             -----------------------
    ..      |            /
    ..  \|H\| |           /
    ..      |          /
    ..      |         /
    ..    0-|---------
    ..      |        |    |                     |
    ..      0      Fstop  Fp                   Nyq

    Where :

        * l_trans_bandwidth = Fp - Fstop in Hz
        * ``freqs`` = `[Fstop, Fp]`


    Notes:

        Adapted from mne.filters, see the documentation of:

        * `mne.filters <https://martinos.org/mne/stable/generated/mne.filter.construct_fir_filter.html>`_

    """

    # normalize frequencies
    _normalized_freqs = [f / nyq for f in freqs]

    if mode == 'highpass':
        if len(freqs) == 1:
            l_freq = freqs[0]
            l_trans_bandwidth = min(max(l_freq * 0.25, 2), l_freq)
            freqs = [l_freq - l_trans_bandwidth / 2, l_freq + l_trans_bandwidth / 2]
            LOGGER.info("Filter Design: assuming {tb} Hz transition band.".format(
                tb=freqs[1] - freqs[0]))
        wp, ws = freqs[1], freqs[0]

    elif mode == 'lowpass':

        if len(freqs) == 1:
            h_freq = freqs[0]
            h_trans_bandwidth = min(max(h_freq * 0.25, 2.), nyq - h_freq)
            freqs = [h_freq-h_trans_bandwidth/2, h_freq + h_trans_bandwidth/2]
            LOGGER.info(
                "IIRFilter: assuming {tb} Hz transition band.".format(tb=freqs[1] - freqs[0]))
        wp, ws = _hz_to_nyq(freqs, nyq)


    elif mode == "bandpass":
        if len(freqs) == 2:
            lofreq, hifreq = freqs
            minfreq = lofreq - 1 if lofreq > 1 else lofreq / 2
            maxfreq = (hifreq + 1 if hifreq < nyq - 1 else (hifreq + nyq) / 2)
            freqs = [minfreq, lofreq, hifreq, maxfreq]
            LOGGER.info("Filter Design: assuming {tb1} and {tb2} Hz transition band.".format(
                tb1=freqs[2] - freqs[1],
                tb2=freqs[3] - freqs[0]))
        wp, ws = _hz_to_nyq([freqs[1], freqs[2]], nyq), _hz_to_nyq([freqs[0], freqs[3]], nyq)

    elif mode == "bandstop":
        if len(freqs) == 2:
            l_freq, h_freq = freqs
            l_trans_bandwidth = min(max(l_freq * 0.25, 2), l_freq)
            h_trans_bandwidth = min(max(h_freq * 0.25, 2.), nyq - h_freq)

            freqs = [l_freq - l_trans_bandwidth / 2, l_freq + l_trans_bandwidth / 2, h_freq-h_trans_bandwidth/2, h_freq + h_trans_bandwidth/2]

            LOGGER.info("Filter Design: assuming {tb1} and {tb2} Hz transition band.".format(
                tb1=freqs[3] - freqs[0],
                tb2=freqs[1] - freqs[2]))
        wp, ws = _hz_to_nyq([freqs[0], freqs[3]], nyq), _hz_to_nyq([freqs[1], freqs[2]], nyq)

    else:
        raise ValueError("Unknown filter mode given: {mode} ".format(mode=mode))

    if mode == 'bandpass':
        freqs = [0] + freqs + [nyq]
        gains = [0, 0, 1, 1, 0, 0]
    elif mode == 'bandstop':
        freqs = [0] + freqs + [nyq]
        gains = [1, 1, 0, 0, 1, 1]
    elif mode == 'highpass':
        freqs = [0] + freqs + [nyq]
        gains = [0, 0, 1, 1]
    elif mode == 'lowpass':
        freqs = [0] + freqs + [nyq]
        gains = [1, 1, 0, 0]
    else:
        raise ValueError("unsupported filter mode: {mode}".format(mode=mode))

    if any([f > nyq for f in freqs]):
        raise ValueError("One of the given frequencies exceeds the "
                         "Nyquist frequency of the signal (%.1f)." % nyq)

    return freqs, gains, wp, ws


def _filter_attenuation(h, freqs, gains):
    """ Compute minimum attenuation at stop frequency.

     Args:
        h (array): Filter coefficients.
        freqs (list): Transition frequencies normalized.
        gains (array):  Filter gain at frequency sampling points.

     Returns:
        att_db: Minimum attenuation per frequency
        att_freq: Frequencies

    Notes:

        Adapted from mne.filters

    """
    freqs = np.array(freqs)
    from scipy.signal import freqz
    _, filt_resp = freqz(h.ravel(), worN=np.pi * freqs)
    filt_resp = np.abs(filt_resp)  # use amplitude response
    filt_resp[np.where(gains == 1)] = 0
    idx = np.argmax(filt_resp)
    att_db = -20 * np.log10(np.maximum(filt_resp[idx], 1e-20))
    att_freq = freqs[idx]
    return att_db, att_freq

def construct_fir_filter(fs, freqs, gains, order, phase, window, design):
    """ Construct coeffs of FIR filter.

    Args:
        fs (float): Nominal sampling rate of the input data.
        order (int): Filter order
        freqs (list): Transition frequencies in Hz.
        mode (str): Filter mode (`lowpass`, `highpass`, `bandstop` or `bandpass`).
        design (str|'firwin2'): Design of the transfert function of the filter.
        phase (str|`linear`): Phase response ("zero", "zero-double" or "minimum").
        window (float|`hamming`): The window to use in FIR design, ("hamming", "hann", or "blackman").

    Returns:
        array h. FIR coeffs.

    Notes:

        Adapted from mne.filters, see the documentation of:

        * `mne.filters <https://martinos.org/mne/stable/generated/mne.filter.construct_fir_filter.html>`_
        * `scipy.signal.firwin2 <https://docs.scipy.org/doc/scipy-0.14.0/reference/generated/scipy.signal.firwin2.html>`_



    """
    nyq = fs/2.
    if design == 'firwin2':
        from scipy.signal import firwin2 as design
    else:
        # not implemented yet
        raise ValueError('firwin, remez and firls have not been implemented yet ')

    # issue a warning if attenuation is less than this
    min_att_db = 12 if phase == 'minimum' else 20

    if freqs[0] != 0 or freqs[-1] != nyq:
        raise ValueError('freq must start at 0 and end an Nyquist (%s), got %s'
                         % (nyq, freqs))
    gains = np.array(gains)

    if window == "kaiser":
        diffs = np.diff(freqs)
        width = min(diffs[diffs > 0])
        beta = signal.kaiser_beta(signal.kaiser_atten(order, width/nyq))
        window = ("kaiser", beta)


    # check zero phase length
    N = int(order)
    if  N % 2 == 0:
        if phase == 'zero':
            LOGGER.info('filter_length must be odd if phase="zero", '
                               'got %s' % N )
            N+=1
        elif phase == 'zero-double' and gains[-1] == 1:
            N += 1
    # construct symmetric (linear phase) filter
    if phase == 'minimum':
        h = design(N * 2 - 1, freqs, gains, fs=fs, window=window)
        h = signal.minimum_phase(h)
    else:
        h = design(N, freqs, gains, fs=fs, window=window)
    assert h.size == N
    att_db, att_freq = _filter_attenuation(h, freqs, gains)
    if phase == 'zero-double':
        att_db += 6
    if att_db < min_att_db:
        att_freq *= fs / 2.
        LOGGER.info('Attenuation at stop frequency %0.1fHz is only %0.1fdB. '
             'Increase filter_length for higher attenuation.'
             % (att_freq, att_db))
    return h



def construct_iir_filter(fs, freqs, mode, order=None, design="butter", pass_loss=3.0, stop_atten=50.0, output="sos"):

    """Calculate an IIR filter kernel for a given sampling rate.

    Args:
        fs (float): Nominal sampling rate of the input data.
        order (int): Filter order
        freqs (list): Transition frequencies in Hz.
        mode (str): Filter mode (`lowpass`, `highpass`, `bandstop` or `bandpass`).
        design (str|'butter'): Design of the transfert function of the filter (`butter`, `cheby1`, `cheby2`, `ellip`, `bessel`)
        pass_loss (float|`3.0`): For Chebyshev and elliptic filters, provides the maximum ripple in the passband. (dB).
        stop_atten (float|`50.0`): For Chebyshev and elliptic filters, provides the minimum attenuation in the stop band. (dB)

    Returns:
        array: sos. IIR coeffs.

    Notes:

        Adapted from mne.filters, see the documentation of:

        * `mne.filters <https://martinos.org/mne/stable/generated/mne.filter.construct_fir_filter.html>`_
        * `scipy.signal.iirfilter <https://docs.scipy.org/doc/scipy-0.14.0/reference/generated/scipy.signal.iirfilter.html>`_
        * `scipy.signal.iirdesign <https://docs.scipy.org/doc/scipy-0.14.0/reference/generated/scipy.signal.iirdesign.html>`_


    """

    _minorder = {"butter": signal.buttord, "cheby1": signal.cheb1ord, "cheby2": signal.cheb2ord, "ellip": signal.ellip}

    nyq = fs / 2.0

    if order:
        # use order-based design
        wn = _hz_to_nyq(freqs, nyq)
        out = signal.iirfilter(N=order, Wn=wn,
                               rp=pass_loss,
                               rs=stop_atten,
                               btype=mode, ftype=design,
                               output=output)
        # sos = signal.iirfilter(N=order, Wn=wn,
        #                         rp=pass_loss,
        #                         rs=stop_atten,
        #                         btype=mode, ftype=design,
        #                         output='sos')
        return out, freqs
    else:
        freqs, gains, wp, ws = design_edges(freqs, nyq, mode)
        out = signal.iirdesign(wp=wp, ws=ws, gstop=stop_atten,
                               gpass=pass_loss,
                               ftype=design, output=output)
        # sos = signal.iirdesign(wp=wp, ws=ws, gstop=stop_atten,
        #                        gpass=pass_loss,
        #                        ftype=design, output='sos')
        return out, freqs

