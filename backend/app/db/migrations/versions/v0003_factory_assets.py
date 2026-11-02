from pymongo.database import Database

VERSION = "0003_factory_assets"

ASSET_COLLECTIONS = {
    "factories": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "organization_id",
                "name",
                "timezone",
                "description",
                "unit_preferences",
                "operating_calendar",
                "created_at",
                "updated_at",
                "archived_at",
            ],
            "additionalProperties": False,
            "properties": {
                "_id": {"bsonType": "objectId"},
                "organization_id": {"bsonType": "objectId"},
                "name": {"bsonType": "string", "minLength": 1, "maxLength": 160},
                "timezone": {"bsonType": "string", "minLength": 1, "maxLength": 80},
                "description": {"bsonType": "string", "maxLength": 4000},
                "unit_preferences": {
                    "bsonType": "object",
                    "required": ["system", "temperature"],
                    "additionalProperties": False,
                    "properties": {
                        "system": {"enum": ["metric", "imperial"]},
                        "temperature": {"enum": ["C", "F"]},
                    },
                },
                "operating_calendar": {
                    "bsonType": "object",
                    "required": ["shifts"],
                    "additionalProperties": False,
                    "properties": {
                        "shifts": {
                            "bsonType": "array",
                            "maxItems": 70,
                            "items": {
                                "bsonType": "object",
                                "required": ["day", "name", "start", "end"],
                                "additionalProperties": False,
                                "properties": {
                                    "day": {
                                        "bsonType": "int",
                                        "minimum": 0,
                                        "maximum": 6,
                                    },
                                    "name": {
                                        "bsonType": "string",
                                        "minLength": 1,
                                        "maxLength": 80,
                                    },
                                    "start": {
                                        "bsonType": "string",
                                        "pattern": r"^(?:[01]\d|2[0-3]):[0-5]\d$",
                                    },
                                    "end": {
                                        "bsonType": "string",
                                        "pattern": r"^(?:[01]\d|2[0-3]):[0-5]\d$",
                                    },
                                },
                            },
                        }
                    },
                },
                "created_at": {"bsonType": "date"},
                "updated_at": {"bsonType": "date"},
                "archived_at": {"bsonType": ["date", "null"]},
                "archive_parent_id": {"bsonType": ["objectId", "null"]},
            },
        }
    },
    "production_lines": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "organization_id",
                "factory_id",
                "name",
                "description",
                "created_at",
                "updated_at",
                "archived_at",
            ],
            "additionalProperties": False,
            "properties": {
                "_id": {"bsonType": "objectId"},
                "organization_id": {"bsonType": "objectId"},
                "factory_id": {"bsonType": "objectId"},
                "name": {"bsonType": "string", "minLength": 1, "maxLength": 160},
                "description": {"bsonType": "string", "maxLength": 4000},
                "created_at": {"bsonType": "date"},
                "updated_at": {"bsonType": "date"},
                "archived_at": {"bsonType": ["date", "null"]},
                "archive_parent_id": {"bsonType": ["objectId", "null"]},
            },
        }
    },
    "machines": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "organization_id",
                "factory_id",
                "line_id",
                "identity",
                "name",
                "machine_type",
                "custom_type_name",
                "capabilities",
                "manufacturer",
                "model",
                "nominal_cycle_time_seconds",
                "capacity_per_hour",
                "operating_state",
                "model_validation_status",
                "created_at",
                "updated_at",
                "archived_at",
            ],
            "additionalProperties": False,
            "properties": {
                "_id": {"bsonType": "objectId"},
                "organization_id": {"bsonType": "objectId"},
                "factory_id": {"bsonType": "objectId"},
                "line_id": {"bsonType": "objectId"},
                "identity": {"bsonType": "string", "minLength": 1, "maxLength": 120},
                "name": {"bsonType": "string", "minLength": 1, "maxLength": 160},
                "machine_type": {
                    "enum": [
                        "conveyor",
                        "processing_station",
                        "cnc_cutting",
                        "drilling",
                        "assembly",
                        "inspection",
                        "packaging",
                        "buffer_storage",
                        "custom",
                    ]
                },
                "custom_type_name": {"bsonType": "string", "maxLength": 120},
                "capabilities": {
                    "bsonType": "array",
                    "maxItems": 32,
                    "items": {"bsonType": "string", "minLength": 1, "maxLength": 120},
                },
                "manufacturer": {"bsonType": "string", "maxLength": 160},
                "model": {"bsonType": "string", "maxLength": 160},
                "nominal_cycle_time_seconds": {"bsonType": ["double", "int", "long"], "minimum": 0},
                "capacity_per_hour": {"bsonType": ["double", "int", "long"], "minimum": 0},
                "operating_state": {
                    "enum": [
                        "running",
                        "idle",
                        "starved",
                        "blocked",
                        "faulted",
                        "maintenance",
                        "offline",
                    ]
                },
                "model_validation_status": {"enum": ["not_validated"]},
                "created_at": {"bsonType": "date"},
                "updated_at": {"bsonType": "date"},
                "archived_at": {"bsonType": ["date", "null"]},
                "archive_parent_id": {"bsonType": ["objectId", "null"]},
            },
        }
    },
    "components": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "organization_id",
                "factory_id",
                "line_id",
                "machine_id",
                "identity",
                "name",
                "component_type",
                "manufacturer",
                "model",
                "created_at",
                "updated_at",
                "archived_at",
            ],
            "additionalProperties": False,
            "properties": {
                "_id": {"bsonType": "objectId"},
                "organization_id": {"bsonType": "objectId"},
                "factory_id": {"bsonType": "objectId"},
                "line_id": {"bsonType": "objectId"},
                "machine_id": {"bsonType": "objectId"},
                "identity": {"bsonType": "string", "minLength": 1, "maxLength": 120},
                "name": {"bsonType": "string", "minLength": 1, "maxLength": 160},
                "component_type": {
                    "enum": [
                        "motor",
                        "bearing",
                        "gearbox",
                        "belt",
                        "controller",
                        "custom",
                    ]
                },
                "manufacturer": {"bsonType": "string", "maxLength": 160},
                "model": {"bsonType": "string", "maxLength": 160},
                "created_at": {"bsonType": "date"},
                "updated_at": {"bsonType": "date"},
                "archived_at": {"bsonType": ["date", "null"]},
                "archive_parent_id": {"bsonType": ["objectId", "null"]},
            },
        }
    },
    "sensors": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "organization_id",
                "factory_id",
                "line_id",
                "machine_id",
                "component_id",
                "identity",
                "name",
                "measurement_type",
                "unit",
                "expected_reporting_interval_seconds",
                "thresholds",
                "calibration",
                "created_at",
                "updated_at",
                "archived_at",
            ],
            "additionalProperties": False,
            "properties": {
                "_id": {"bsonType": "objectId"},
                "organization_id": {"bsonType": "objectId"},
                "factory_id": {"bsonType": "objectId"},
                "line_id": {"bsonType": "objectId"},
                "machine_id": {"bsonType": "objectId"},
                "component_id": {"bsonType": "objectId"},
                "identity": {"bsonType": "string", "minLength": 1, "maxLength": 120},
                "name": {"bsonType": "string", "minLength": 1, "maxLength": 160},
                "measurement_type": {
                    "enum": [
                        "temperature",
                        "pressure",
                        "vibration",
                        "speed",
                        "current",
                        "voltage",
                        "power",
                        "flow",
                        "level",
                        "proximity",
                        "position",
                        "force",
                        "humidity",
                        "count",
                        "custom",
                    ]
                },
                "unit": {"bsonType": "string", "minLength": 1, "maxLength": 32},
                "expected_reporting_interval_seconds": {
                    "bsonType": ["double", "int", "long"],
                    "minimum": 0.001,
                },
                "thresholds": {
                    "bsonType": "object",
                    "required": ["minimum", "maximum"],
                    "additionalProperties": False,
                    "properties": {
                        "minimum": {"bsonType": ["double", "int", "long", "null"]},
                        "maximum": {"bsonType": ["double", "int", "long", "null"]},
                    },
                },
                "calibration": {
                    "bsonType": "object",
                    "required": [
                        "last_calibrated_at",
                        "calibration_due_at",
                        "offset",
                        "scale",
                        "notes",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "last_calibrated_at": {"bsonType": ["date", "null"]},
                        "calibration_due_at": {"bsonType": ["date", "null"]},
                        "offset": {"bsonType": ["double", "int", "long", "null"]},
                        "scale": {"bsonType": ["double", "int", "long", "null"]},
                        "notes": {"bsonType": "string", "maxLength": 1000},
                    },
                },
                "created_at": {"bsonType": "date"},
                "updated_at": {"bsonType": "date"},
                "archived_at": {"bsonType": ["date", "null"]},
                "archive_parent_id": {"bsonType": ["objectId", "null"]},
            },
        }
    },
    "asset_audit_logs": {
        "$jsonSchema": {
            "bsonType": "object",
            "required": [
                "organization_id",
                "actor_user_id",
                "entity_type",
                "entity_id",
                "action",
                "changes",
                "created_at",
            ],
            "additionalProperties": False,
            "properties": {
                "_id": {"bsonType": "objectId"},
                "organization_id": {"bsonType": "objectId"},
                "actor_user_id": {"bsonType": "objectId"},
                "entity_type": {
                    "enum": ["factory", "line", "machine", "component", "sensor"]
                },
                "entity_id": {"bsonType": "objectId"},
                "action": {"enum": ["created", "updated", "archived", "reopened"]},
                "changes": {"bsonType": "object"},
                "created_at": {"bsonType": "date"},
            },
        }
    },
}


def upgrade(database: Database) -> None:
    for collection_name, validator in ASSET_COLLECTIONS.items():
        if collection_name in database.list_collection_names():
            database.command(
                {
                    "collMod": collection_name,
                    "validator": validator,
                    "validationLevel": "strict",
                    "validationAction": "error",
                }
            )
        else:
            database.create_collection(
                collection_name,
                validator=validator,
                validationLevel="strict",
                validationAction="error",
            )

    for factory in database.factories.find({"timezone": {"$exists": False}}):
        database.factories.update_one(
            {"_id": factory["_id"]},
            {
                "$set": {
                "timezone": "UTC",
                "description": "",
                "unit_preferences": {"system": "metric", "temperature": "C"},
                "operating_calendar": {"shifts": []},
                "archived_at": None,
                    "archive_parent_id": None,
                }
            },
        )
    database.production_lines.create_index(
        [("organization_id", 1), ("factory_id", 1), ("_id", 1)],
        name="ix_lines_organization_factory",
    )
    database.machines.create_index(
        [("organization_id", 1), ("identity", 1)],
        unique=True,
        name="uq_machines_organization_identity",
    )
    database.machines.create_index(
        [("organization_id", 1), ("line_id", 1), ("_id", 1)],
        name="ix_machines_organization_line",
    )
    database.components.create_index(
        [("organization_id", 1), ("identity", 1)],
        unique=True,
        name="uq_components_organization_identity",
    )
    database.components.create_index(
        [("organization_id", 1), ("machine_id", 1), ("_id", 1)],
        name="ix_components_organization_machine",
    )
    database.sensors.create_index(
        [("organization_id", 1), ("identity", 1)],
        unique=True,
        name="uq_sensors_organization_identity",
    )
    database.sensors.create_index(
        [("organization_id", 1), ("component_id", 1), ("_id", 1)],
        name="ix_sensors_organization_component",
    )
    database.asset_audit_logs.create_index(
        [("organization_id", 1), ("created_at", -1)],
        name="ix_asset_audit_organization_created",
    )
    database.asset_audit_logs.create_index(
        [("organization_id", 1), ("entity_type", 1), ("entity_id", 1)],
        name="ix_asset_audit_entity",
    )
