"""
RigArchitect Database Schemas

Each Pydantic model below maps to a MongoDB collection (lowercased class name).
These schemas are used for validation in API endpoints and by the database helper.
"""
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


# Core domain schemas
class Component(BaseModel):
    """
    Generic PC component. "type" controls required fields for compatibility checks.
    Supported types: cpu, motherboard, ram, gpu, storage, psu, case, cooler
    """
    name: str
    type: Literal[
        "cpu",
        "motherboard",
        "ram",
        "gpu",
        "storage",
        "psu",
        "case",
        "cooler",
    ]
    brand: Optional[str] = None
    model: Optional[str] = None

    # Compatibility attributes (optional per type)
    socket: Optional[str] = Field(None, description="CPU/Motherboard socket")
    chipset: Optional[str] = None
    tdp: Optional[int] = Field(None, ge=0, description="Thermal design power in Watts")
    ram_type: Optional[str] = Field(None, description="DDR4/DDR5 etc")
    ram_speed: Optional[int] = Field(None, ge=0)
    ram_slots: Optional[int] = Field(None, ge=0)
    pcie_version: Optional[str] = None
    gpu_length_mm: Optional[int] = Field(None, ge=0)
    max_gpu_length_mm: Optional[int] = Field(None, ge=0, description="Case spec")
    psu_wattage: Optional[int] = Field(None, ge=0)
    psu_form_factor: Optional[str] = Field(None, description="ATX/SFX/SFX-L")
    case_supported_psu: Optional[List[str]] = None
    case_motherboard_support: Optional[List[str]] = Field(
        None, description="e.g., [Mini-ITX, Micro-ATX, ATX, E-ATX]"
    )
    motherboard_form_factor: Optional[str] = None
    cooler_height_mm: Optional[int] = None
    case_max_cooler_height_mm: Optional[int] = None
    storage_interface: Optional[str] = Field(
        None, description="NVMe, SATA, PCIe Gen4 x4, etc"
    )
    m2_slots: Optional[int] = None

    price: Optional[float] = Field(None, ge=0)
    image: Optional[str] = None
    url: Optional[str] = None


class BuildComponent(BaseModel):
    component_id: str
    type: str


class Build(BaseModel):
    title: str
    description: Optional[str] = None
    creator_id: Optional[str] = None
    is_anchor: bool = False
    components: List[BuildComponent]
    total_price: Optional[float] = Field(None, ge=0)
    likes: int = 0


class Comment(BaseModel):
    build_id: str
    author_id: Optional[str] = None
    author_name: Optional[str] = None
    content: str


class Like(BaseModel):
    build_id: str
    user_id: str


class User(BaseModel):
    name: str
    email: str
    avatar: Optional[str] = None
    is_admin: bool = False
