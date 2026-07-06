"""Семейства документов (YAML) вместо hardcode в .py."""

from .registry import DocumentFamily, FamilyRegistry, get_family_registry

__all__ = ["DocumentFamily", "FamilyRegistry", "get_family_registry"]