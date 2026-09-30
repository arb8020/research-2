"""Synthetic (rolled, random-weight) models.

`roll` shrinks a hub config; `features` lists what an implementation of it must handle."""

from kelpie_models.synth.features import Checklist, features
from kelpie_models.synth.roll import RolledConfig, RollPlan, roll

__all__ = ["Checklist", "RollPlan", "RolledConfig", "features", "roll"]
