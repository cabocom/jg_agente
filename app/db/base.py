"""Configuración base de SQLAlchemy y convenciones de nomenclatura para jg_agente.

Asegura que todos los objetos de base de datos (tablas, índices, claves primarias,
claves foráneas y restricciones) generados por el Core posean de manera estricta
el prefijo 'core_'.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Convención de nombres estricta con prefijo core_
core_naming_convention = {
    "ix": "core_ix_%(column_0_label)s",
    "uq": "core_uq_%(table_name)s_%(column_0_name)s",
    "ck": "core_ck_%(table_name)s_%(constraint_name)s",
    "fk": "core_fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "core_pk_%(table_name)s",
}

core_metadata = MetaData(naming_convention=core_naming_convention)


class Base(DeclarativeBase):
    """Clase base declarativa para todas las entidades ORM del Core."""

    metadata = core_metadata
