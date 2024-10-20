from typing import Optional, Tuple

import torch
from torch import nn


def make_filterbanks(
    n_fft: int = 4096,
    n_hop: int = 1024,
    center: bool = False,
) -> Tuple[nn.Module, nn.Module]:

    window = nn.Parameter(torch.hann_window(n_fft), requires_grad=False)

    encoder = TorchSTFT(n_fft=n_fft, n_hop=n_hop, window=window, center=center)
    decoder = TorchISTFT(n_fft=n_fft, n_hop=n_hop, window=window, center=center)
    return encoder, decoder


class TorchSTFT(nn.Module):
    """Multichannel Short-Time-Fourier Forward transform
    uses hard coded hann_window.
    Args:
        n_fft (int, optional): transform FFT size. Defaults to 4096.
        n_hop (int, optional): transform hop size. Defaults to 1024.
        center (bool, optional): If True, the signals first window is
            zero padded. Centering is required for a perfect
            reconstruction of the signal. However, during training
            of spectrogram models, it can safely turned off.
            Defaults to `true`
        window (nn.Parameter, optional): window function
    """

    def __init__(
        self,
        n_fft: int = 4096,
        n_hop: int = 1024,
        center: bool = False,
        window: Optional[nn.Parameter] = None,
    ):
        super(TorchSTFT, self).__init__()
        if window is None:
            self.window = nn.Parameter(torch.hann_window(n_fft), requires_grad=False)
        else:
            self.window = window

        self.n_fft = n_fft
        self.n_hop = n_hop
        self.center = center

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """STFT forward path
        Args:
            x (Tensor): audio waveform of
                shape (nb_samples, nb_channels, nb_timesteps)
        Returns:
            STFT (Tensor): complex stft of
                shape (nb_samples, nb_channels, nb_bins, nb_frames, complex=2)
                last axis is stacked real and imaginary
        """

        shape = x.size() # (nb_samples, nb_channels, nb_timesteps)

        # pack batch
        x = x.view(-1, shape[-1])

        complex_stft = torch.stft(
            x,
            n_fft=self.n_fft,
            hop_length=self.n_hop,
            window=self.window,
            center=self.center,
            normalized=False,
            onesided=True,
            pad_mode="reflect",
            return_complex=True,
        )
        stft_f = torch.view_as_real(complex_stft)
        # unpack batch
        stft_f = stft_f.view(shape[:-1] + stft_f.shape[-3:])
        return stft_f


class TorchISTFT(nn.Module):
    """Multichannel Inverse-Short-Time-Fourier functional
    wrapper for torch.istft to support batches
    Args:
        STFT (Tensor): complex stft of
            shape (nb_samples, nb_channels, nb_bins, nb_frames, complex=2)
            last axis is stacked real and imaginary
        n_fft (int, optional): transform FFT size. Defaults to 4096.
        n_hop (int, optional): transform hop size. Defaults to 1024.
        window (callable, optional): window function
        center (bool, optional): If True, the signals first window is
            zero padded. Centering is required for a perfect
            reconstruction of the signal. However, during training
            of spectrogram models, it can safely turned off.
            Defaults to `true`
        length (int, optional): audio signal length to crop the signal
    Returns:
        x (Tensor): audio waveform of
            shape (nb_samples, nb_channels, nb_timesteps)
    """

    def __init__(
        self,
        n_fft: int = 4096,
        n_hop: int = 1024,
        center: bool = False,
        sample_rate: float = 44100.0,
        window: Optional[nn.Parameter] = None,
    ) -> None:
        super(TorchISTFT, self).__init__()

        self.n_fft = n_fft
        self.n_hop = n_hop
        self.center = center
        self.sample_rate = sample_rate

        if window is None:
            self.window = nn.Parameter(torch.hann_window(n_fft), requires_grad=False)
        else:
            self.window = window

    def forward(self, X: torch.Tensor, length: Optional[int] = None) -> torch.Tensor:
        shape = X.size()
        X = X.reshape(-1, shape[-3], shape[-2], shape[-1])

        y = torch.istft(
            torch.view_as_complex(X),
            n_fft=self.n_fft,
            hop_length=self.n_hop,
            window=self.window,
            center=self.center,
            normalized=False,
            onesided=True,
            length=length,
        )

        y = y.reshape(shape[:-3] + y.shape[-1:])

        return y


class ComplexNorm(nn.Module):
    r"""Compute the norm of complex tensor input.

    Extension of `torchaudio.functional.complex_norm` with mono

    Args:
        mono (bool): Downmix to single channel after applying power norm
            to maximize
    """

    def __init__(self, mono: bool = False):
        super(ComplexNorm, self).__init__()
        self.mono = mono

    def forward(self, spec: torch.Tensor) -> torch.Tensor:
        """
        Args:
            spec: complex_tensor (Tensor): Tensor shape of
                `(..., complex=2)`

        Returns:
            Tensor: Power/Mag of input
                `(...,)`
        """
        # take the magnitude

        spec = torch.abs(torch.view_as_complex(spec))

        # downmix in the mag domain to preserve energy
        if self.mono:
            spec = torch.mean(spec, 1, keepdim=True)

        return spec


class AudioEncoder(nn.Module):
    def __init__(self, n_fft, n_hop, sample_rate, num_channels):
        super(AudioEncoder, self).__init__()
        self.stft = TorchSTFT(n_fft=n_fft, n_hop=n_hop)
        self.complex_norm = ComplexNorm(mono=num_channels == 1)

    @torch.no_grad()
    def forward(self, x):
        return self.complex_norm(self.stft(x))
