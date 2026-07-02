"""
Модели домена (Pydantic v2).
"""

from __future__ import annotations
import json
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class CableMark(BaseModel):
    """Разобранная марка кабеля."""

    full_mark: str = Field(..., description="Исходная строка марки")
    brand: str = Field(..., description="Базовая марка (ВВГ, ПВС, ККЗ МК и т.д.)")
    fire_class: str | None = Field(None, description="Пожарная категория")
    cores: int = Field(..., ge=1, description="Количество жил/элементов")
    groups: int = Field(1, ge=1, description="Количество групп (пар/троек)")
    size: float = Field(..., gt=0, description="Сечение, мм²")
    material: str | None = Field(None)
    voltage: float | None = Field(None)
    has_armor: bool = Field(False)
    is_lan: bool = Field(False)
    extras: dict[str, Any] = Field(default_factory=dict)

    @field_validator("cores", "groups", mode="before")
    @classmethod
    def _to_int(cls, v: Any) -> int:
        if isinstance(v, str):
            v = v.strip()
        return int(v)

    model_config = {"str_strip_whitespace": True, "validate_assignment": True}

"""---Модели расчета---"""
class TestItem(BaseModel):
    """Элемент прайс-листа."""

    id: int | None = None
    code: str = Field(..., min_length=2)
    name: str = Field(...)
    base_cost: float = Field(..., ge=0)
    category: str | None = None
    method: str | None = None
    rule_type: Literal["fixed", "per_core", "per_group", "time_based"] = "fixed"
    rule_params: dict[str, Any] = Field(default_factory=dict)


class CalculationLine(BaseModel):
    """Строка расчёта."""

    test_item_id: int
    test_name: str
    base_cost: float
    multiplier: float = 1.0
    hours: float | None = None
    final_cost: float
    note: str | None = None


class Calculation(BaseModel):
    """Полный расчёт по марке."""

    id: int | None = None
    mark: str
    parsed_mark: CableMark
    total_cost_without_vat: float
    vat_rate: float = 0.22
    total_cost_with_vat: float
    lines: list[CalculationLine] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    source: Literal["manual", "pdf"] = "manual"
    output_path: str | None = None
    
    
"""---Модели испытаний---"""
class TestItemCreate(BaseModel):
    """Модель для создания нового испытания (через CLI или импорт из Excel)."""
    code: str = Field(
        ...,
        min_length=3,
        max_length=64,
        pattern=r"^[a-z0-9_]+$",
        description="Уникальный код теста (slug). Пример: resistance_core, temp_low, voltage"
    )
    name: str = Field(..., min_length=5, description="Полное наименование испытания")
    base_cost: float = Field(..., gt=0, description="Базовая стоимость без НДС, руб.")
    category: str = Field(..., description="Категория испытания (из прайс-листа)")
    method: Optional[str] = Field(None, description="ГОСТ / метод испытания")
    rule_type: Literal["fixed", "per_core", "per_group", "time_based"] = "fixed"
    rule_params: dict[str, Any] = Field(
        default_factory=dict,
        description="Дополнительные параметры правила (например: {'default_hours': 48, 'hour_cost': 350})"
    )

    @field_validator("rule_params", mode="before")
    @classmethod
    def parse_rule_params(cls, v: Any) -> dict[str, Any]:
        """Позволяет передавать rule_params как JSON-строку при импорте из Excel."""
        if isinstance(v, str):
            try:
                return json.loads(v) if v.strip() else {}
            except json.JSONDecodeError:
                return {}
        return v or {}


class TestItemUpdate(BaseModel):
    """Модель для частичного обновления испытания 
    (обновляются только переданные поля)."""
    name: Optional[str] = None
    base_cost: Optional[float] = Field(None, gt=0)
    category: Optional[str] = None
    method: Optional[str] = None
    rule_type: Optional[Literal["fixed", "per_core", "per_group", "time_based"]] = None
    rule_params: Optional[dict[str, Any]] = None


"""---Модели извлечения из PDF---"""


class CableMarkMatch(BaseModel):
    """Найденная в документе марка кабеля."""

    mark: str
    context: str | None = None
    document: str | None = None


class CableMarkRecord(BaseModel):
    """Запись в накопительной таблице марок кабелей."""

    id: int | None = None
    full_mark: str = Field(..., description="Полная марка с размерами и надписями")
    brand: str = Field(..., description="Буквенная часть без пожарного обозначения")
    fire_class: str | None = Field(None, description="Класс пожарной безопасности")
    cores_count: int = Field(..., ge=1, description="Количество ТПЖ")
    structural_element_type: str | None = Field(
        None, description="Вид структурного элемента: жила, пара, тройка"
    )
    structural_elements_count: int | None = Field(
        None, ge=1, description="Количество структурных элементов"
    )
    characteristic_size: float = Field(..., gt=0, description="Сечение или диаметр ТПЖ")
    size_unit: Literal["mm2", "mm"] = Field("mm2", description="mm2 — сечение, mm — диаметр")
    document: str | None = Field(None, description="Документ, по которому выпускается")
    source: str | None = Field(None, description="Источник (путь PDF и т.д.)")
    created_at: datetime | None = None


class KPMarkLine(BaseModel):
    """Строка КП — одна марка с итогами расчёта."""

    mark: str
    total_without_vat: float = Field(..., ge=0)
    vat_amount: float = Field(..., ge=0)
    total_with_vat: float = Field(..., ge=0)
    calculation_id: int | None = None


class CommercialProposal(BaseModel):
    """Коммерческое предложение по нескольким маркам."""

    customer: str = Field("", description="Заказчик / изготовитель")
    subject: str = Field(
        "Проведение периодических испытаний",
        description="Предмет КП",
    )
    note: str | None = Field(None, description="Дополнительный текст из письма")
    marks: list[KPMarkLine] = Field(default_factory=list)
    vat_rate: float = Field(0.22, ge=0, le=1)
    validity_days: int = Field(30, ge=1)
    created_at: datetime = Field(default_factory=datetime.now)
    output_path: str | None = None

    @property
    def total_without_vat(self) -> float:
        return round(sum(m.total_without_vat for m in self.marks), 2)

    @property
    def total_vat(self) -> float:
        return round(sum(m.vat_amount for m in self.marks), 2)

    @property
    def total_with_vat(self) -> float:
        return round(sum(m.total_with_vat for m in self.marks), 2)


class ClimaticTestSettings(BaseModel):
    """Время выдержки по умолчанию для климатических испытаний (часы)."""

    temp_low: float = Field(2.0, gt=0, description="Пониженная температура")
    temp_high: float = Field(2.0, gt=0, description="Повышенная температура")
    temp_cycling: float = Field(2.0, gt=0, description="Изменение температур")
    humidity: float = Field(48.0, gt=0, description="Повышенная влажность")
    solar_radiation: float = Field(24.0, gt=0, description="Солнечная радиация")


OrganizationRole = Literal["customer", "manufacturer", "dealer", "unknown"]
OrganizationType = Literal[
    "manufacturer",
    "certification_body",
    "testing_center",
    "dealer",
    "unknown",
]


class OrganizationExtract(BaseModel):
    """Организация, извлечённая из текста заявки (до сохранения в БД)."""

    name: str = Field(..., min_length=2)
    address: str | None = None
    postal_code: str | None = None
    phone: str | None = None
    email: str | None = None
    inn: str | None = None
    kpp: str | None = None
    is_accredited: bool = False
    fsa_registry_number: str | None = None
    org_type: OrganizationType = "unknown"
    role: OrganizationRole = "unknown"
    confidence: float = Field(0.5, ge=0, le=1)


class Organization(BaseModel):
    """Организация в справочнике БД."""

    id: int | None = None
    name: str
    name_normalized: str
    address: str | None = None
    postal_code: str | None = None
    phone: str | None = None
    email: str | None = None
    inn: str | None = None
    kpp: str | None = None
    is_accredited: bool = False
    fsa_registry_number: str | None = None
    org_type: OrganizationType = "unknown"
    source: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OrderMark(BaseModel):
    """Марка внутри заказа."""

    id: int | None = None
    order_id: int | None = None
    calculation_id: int
    cable_mark_id: int | None = None
    manufacturer_org_id: int | None = None
    mark: str
    total_without_vat: float
    total_with_vat: float


class Order(BaseModel):
    """Заказ: одна заявка + расчёты + КП."""

    id: int | None = None
    customer_org_id: int | None = None
    manufacturer_org_id: int | None = None
    subject: str = ""
    note: str | None = None
    status: Literal["draft", "kp_generated", "completed"] = "kp_generated"
    total_without_vat: float = 0.0
    total_with_vat: float = 0.0
    vat_rate: float = 0.22
    document_extraction_id: int | None = None
    kp_output_path: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    marks: list[OrderMark] = Field(default_factory=list)


class PdfExtractionResult(BaseModel):
    """Результат извлечения из заявки (PDF, Word .docx)."""

    source_path: str
    source_type: Literal["pdf", "docx", "unknown"] = "pdf"
    page_count: int
    text: str
    tables: list[list[list[str]]] = Field(default_factory=list)
    cable_marks: list[CableMarkMatch] = Field(default_factory=list)
    organizations: list[OrganizationExtract] = Field(default_factory=list)
    customer_name: str = ""
    manufacturer_name: str = ""
    is_scanned: bool = False
    ocr_used: bool = False
    extracted_at: datetime = Field(default_factory=datetime.now)