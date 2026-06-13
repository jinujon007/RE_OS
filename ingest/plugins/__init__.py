"""
RE_OS — Ingest Plugin Registry (Sprint 61)
All 8 DataPlugin adapters are exported from this module so the scheduler
and IngestEngine can import them via a single line::

    from ingest.plugins import RERAPlugin, IGRPlugin, ...
"""
from ingest.plugins.rera_plugin import RERAPlugin
from ingest.plugins.igr_plugin import IGRPlugin
from ingest.plugins.kaveri_bhoomi_plugin import KaveriBhoomiPlugin
from ingest.plugins.portal_plugin import PortalPlugin
from ingest.plugins.developer_plugin import DeveloperPlugin
from ingest.plugins.news_plugin import NewsPlugin
from ingest.plugins.distressed_plugin import DistressedPlugin
from ingest.plugins.bbmp_plugin import BBMPPlugin
from ingest.plugins.demand_plugin import DemandPlugin
from ingest.plugins.gcc_plugin import GCCPlugin
from ingest.plugins.land_supply_plugin import LandSupplyPlugin
from ingest.plugins.govt_policy_plugin import GovtPolicyPlugin
from ingest.plugins.kaveri_deeds_plugin import KaveriDeedsPlugin
from ingest.plugins.tender_plugin import TenderPlugin

__all__ = [
    "RERAPlugin",
    "IGRPlugin",
    "KaveriBhoomiPlugin",
    "PortalPlugin",
    "DeveloperPlugin",
    "NewsPlugin",
    "DistressedPlugin",
    "BBMPPlugin",
    "DemandPlugin",
    "GCCPlugin",
    "LandSupplyPlugin",
    "GovtPolicyPlugin",
    "KaveriDeedsPlugin",
    "TenderPlugin",
]
