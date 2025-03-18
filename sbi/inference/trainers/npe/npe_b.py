# This file is part of sbi, a toolkit for simulation-based inference. sbi is licensed
# under the Apache License Version 2.0, see <https://www.apache.org/licenses/>

from typing import Any, Callable, Optional, Union

import torch
from torch import Tensor
from torch.distributions import Distribution

import sbi.utils as utils
from sbi.inference.trainers.npe.npe_base import PosteriorEstimator
from sbi.sbi_types import TensorboardSummaryWriter
from sbi.utils.sbiutils import del_entries


class NPE_B(PosteriorEstimator):
    def __init__(
        self,
        prior: Optional[Distribution] = None,
        density_estimator: Union[str, Callable] = "maf",
        device: str = "cpu",
        logging_level: Union[int, str] = "WARNING",
        summary_writer: Optional[TensorboardSummaryWriter] = None,
        show_progress_bars: bool = True,
    ):
        r"""NPE-B [1].

        [1] _Flexible statistical inference for mechanistic models of neural dynamics_,
            Lueckmann, Gonçalves et al., NeurIPS 2017,
            https://arxiv.org/abs/1711.01861.

        Like all NPE methods, this method trains a deep neural density estimator to
        directly approximate the posterior. Also like all other NPE methods, in the
        first round, this density estimator is trained with a maximum-likelihood loss.

        This class implements NPE-B. NPE-B trains across multiple rounds with a
        an importance-weighted log-loss. Unlike NPE-A the loss will make training
        directly converge to the true posterior.
        Thus, SNPE-B is not limited to Gaussian proposal.

        Args:
            prior: A probability distribution that expresses prior knowledge about the
                parameters, e.g. which ranges are meaningful for them.
            density_estimator: If it is a string, use a pre-configured network of the
                provided type (one of nsf, maf, mdn, made). Alternatively, a function
                that builds a custom neural network can be provided. The function will
                be called with the first batch of simulations (theta, x), which can
                thus be used for shape inference and potentially for z-scoring. It
                needs to return a PyTorch `nn.Module` implementing the density
                estimator. The density estimator needs to provide the methods
                `.log_prob` and `.sample()`.
            device: Training device, e.g., "cpu", "cuda" or "cuda:{0, 1, ...}".
            logging_level: Minimum severity of messages to log. One of the strings
                INFO, WARNING, DEBUG, ERROR and CRITICAL.
            summary_writer: A tensorboard `SummaryWriter` to control, among others, log
                file location (default is `<current working directory>/logs`.)
            show_progress_bars: Whether to show a progressbar during training.
        """

        kwargs = del_entries(locals(), entries=("self", "__class__"))
        super().__init__(**kwargs)

    def _log_prob_proposal_posterior(
        self,
        theta: Tensor,
        x: Tensor,
        masks: Tensor,
        proposal: Optional[Any],
    ) -> Tensor:
        """
        Return importance-weighted log probability (Lueckmann, Goncalves et al., 2017).

        Args:
            theta: Batch of parameters θ.
            x: Batch of data.
            masks: Whether to retrain with prior loss (for each prior sample).
            proposal: Proposal distribution.

        Returns:
            Importance-weighted log-probability of the proposal posterior.
        """

        # Evaluate prior
        utils.assert_all_finite(self._prior.log_prob(theta), "prior eval")
        prior = torch.exp(self._prior.log_prob(theta))

        # Evaluate proposal
        # (as theta comes from prior and proposal from previous rounds,
        # the last proposal is actually a mixture of the prior
        # and of all the previous proposals with coefficients 1/round)
        prop = 1.0 / (self._round + 1)
        proposal = torch.zeros(theta.size(0), device=theta.device)

        for density in self._proposal_roundwise:
            utils.assert_all_finite(density.log_prob(theta), "proposal eval")
            proposal += prop * torch.exp(density.log_prob(theta))

        # Construct the importance weights
        importance_weights = prior / proposal

        return importance_weights * self._neural_net.log_prob(theta.unsqueeze(0), x)
