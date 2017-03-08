import numpy as np
from scipy.special import gamma

class BasePrior(object):
    def __init__(self):
        self.support = (-np.inf, np.inf)

    def logprob(self, x):
        raise NotImplementedError

    def __repr__(self):
        return self.__class__.__name__

class UninformativePrior(BasePrior):
    def logprob(self, x):
        return 0.

class GammaPrior(BasePrior):
    def __init__(self, shape=0.3, scale=1.3):
        self.shape = shape
        self.scale = scale
        self.support = (1e-8, np.inf)

    def logprob(self, x):
        return -np.log(gamma(self.shape)) - self.scale * np.log(self.scale) + (self.shape - 1) * x - x / self.scale

    def __repr__(self):
        return 'GammaPrior(shape={}, scale={})'.format(self.shape, self.scale)

class NormalPrior(BasePrior):
    def __init__(self, mean=0., var=0.1):
        self.mean = mean
        self.var = var
        self.support = (-np.inf, np.inf)

    def logprob(self, x):
        return -0.5*np.log(2 * np.pi) - np.log(self.var) - (x - self.mean)**2 / (2 * self.var**2)

    def __repr__(self):
        return 'NormalPrior(mean={}, var={})'.format(self.mean, self.var)

class LogNormalPrior(BasePrior):
    def __init__(self, mean=0., var=0.1, support=(1e-2, np.inf)):
        self.mean = mean
        self.var = var
        self.support = support

    def logprob(self, x):
        return -0.5*np.log(2 * np.pi) - np.log(self.var) - (np.log(x) - self.mean)**2 / (2 * self.var**2)

    def __repr__(self):
        return 'LogNormalPrior(mean={}, var={})'.format(self.mean, self.var)