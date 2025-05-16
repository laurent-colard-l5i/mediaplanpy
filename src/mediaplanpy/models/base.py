"""
Base model for mediaplanpy.

This module provides the base model class that all models in the package
will inherit from, providing common functionality.
"""

import json
import uuid
import os
from typing import Any, Dict, List, Optional, ClassVar
from datetime import date, datetime
from decimal import Decimal  # Added import
import copy

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, field_validator, model_validator

from mediaplanpy.exceptions import ValidationError, SchemaVersionError
from mediaplanpy.schema import SchemaValidator, get_current_version

# Define constants
EXPORTS_SUBDIR = "exports"

class BaseModel(PydanticBaseModel):
    """
    Base model for all mediaplanpy models.

    Extends Pydantic's BaseModel to provide additional functionality
    specific to media plans.
    """

    # Schema version support
    SCHEMA_VERSION: ClassVar[str] = "v1.0.0"

    # Model configuration
    model_config = ConfigDict(
        # Allow extra fields for forward compatibility
        extra='allow',
        # Use JSON serialization for dates
        json_encoders={
            datetime: lambda dt: dt.isoformat(),
            date: lambda d: d.isoformat(),
        },
        # Validate on assignment
        validate_assignment=True,
        # Allow population by field name
        populate_by_name=True,
        # Use objects for conversion from dict
        from_attributes=True
    )

    def to_dict(self, exclude_none: bool = True) -> Dict[str, Any]:
        """
        Convert the model to a dictionary.

        Args:
            exclude_none: Whether to exclude None values from the output.

        Returns:
            A dictionary representation of the model.
        """
        # First, get the Pydantic model dump as a dictionary
        data = self.model_dump(exclude_none=exclude_none)

        # Process the dictionary to convert date/datetime objects to strings
        # and decimal objects to numbers
        def process_value(value):
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            elif isinstance(value, Decimal):
                return float(value)
            elif isinstance(value, dict):
                return {k: process_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [process_value(item) for item in value]
            return value

        # Process all values in the dictionary
        processed_data = {key: process_value(value) for key, value in data.items()}
        return processed_data

    def to_json(self, exclude_none: bool = True, indent: int = 2) -> str:
        """
        Convert the model to a JSON string.

        Args:
            exclude_none: Whether to exclude None values from the output.
            indent: Number of spaces for indentation.

        Returns:
            A JSON string representation of the model.
        """
        return json.dumps(self.to_dict(exclude_none=exclude_none), indent=indent)

    def validate_model(self) -> List[str]:
        """
        Validate the model against additional rules.

        This method is meant to be overridden by subclasses to add additional
        validation rules beyond what Pydantic provides.

        Returns:
            A list of validation error messages, if any.
        """
        return []

    def assert_valid(self) -> None:
        """
        Assert that the model is valid.

        Raises:
            ValidationError: If the model fails validation.
        """
        errors = self.validate_model()
        if errors:
            raise ValidationError("\n".join(errors))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseModel":
        """
        Create a model instance from a dictionary.

        Args:
            data: Dictionary containing the model data.

        Returns:
            A new model instance.

        Raises:
            ValidationError: If the data fails validation.
            SchemaVersionError: If the data uses an incompatible schema version.
        """
        try:
            # Check schema version if applicable
            if hasattr(cls, "check_schema_version"):
                cls.check_schema_version(data)

            # Create instance
            return cls.model_validate(data)
        except Exception as e:
            raise ValidationError(f"Validation failed for {cls.__name__}: {str(e)}")

    @classmethod
    def from_json(cls, json_str: str) -> "BaseModel":
        """
        Create a model instance from a JSON string.

        Args:
            json_str: JSON string containing the model data.

        Returns:
            A new model instance.

        Raises:
            ValidationError: If the JSON string fails validation.
        """
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON: {str(e)}")

    @classmethod
    def import_from_json(cls, file_path: str) -> "BaseModel":
        """
        Create a model instance from a JSON file.

        Args:
            file_path: Path to the JSON file.

        Returns:
            A new model instance.

        Raises:
            ValidationError: If the file cannot be read or fails validation.
        """
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

            return cls.from_dict(data)
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON in file {file_path}: {str(e)}")
        except Exception as e:
            raise ValidationError(f"Failed to load from file {file_path}: {str(e)}")

    def export_to_json(self, file_path: Optional[str] = None, indent: int = 2) -> str:
        """
        Save the model to a JSON file.

        Args:
            file_path: Path where the file should be saved. If None, saves to
                      exports/{mediaplan_id}.json.
            indent: Number of spaces for indentation.

        Returns:
            The path to the saved file.

        Raises:
            ValidationError: If the file cannot be written.
        """
        try:
            # Generate default path if not provided
            if file_path is None:
                # Create exports directory if it doesn't exist
                if not os.path.exists(EXPORTS_SUBDIR):
                    os.makedirs(EXPORTS_SUBDIR, exist_ok=True)

                # Determine filename based on model type
                if hasattr(self, 'meta') and hasattr(self.meta, 'id'):
                    # For MediaPlan, use meta.id
                    model_id = self.meta.id
                elif hasattr(self, 'id'):
                    # For other models with id field
                    model_id = self.id
                else:
                    # Generic fallback
                    model_id = f"export_{uuid.uuid4().hex[:8]}"

                # Sanitize ID for use as a filename
                safe_id = model_id.replace('/', '_').replace('\\', '_')

                # Generate path: exports/{model_id}.json
                file_path = os.path.join(EXPORTS_SUBDIR, f"{safe_id}.json")
            else:
                # If path doesn't include exports directory and is just a filename,
                # add the exports directory prefix
                if not os.path.dirname(file_path) and not os.path.isabs(file_path):
                    # Create exports directory if it doesn't exist
                    if not os.path.exists(EXPORTS_SUBDIR):
                        os.makedirs(EXPORTS_SUBDIR, exist_ok=True)

                    file_path = os.path.join(EXPORTS_SUBDIR, file_path)
                else:
                    # Ensure the directory exists for the provided path
                    target_dir = os.path.dirname(file_path)
                    if target_dir and not os.path.exists(target_dir):
                        os.makedirs(target_dir, exist_ok=True)

            # Write the JSON file
            with open(file_path, 'w') as f:
                json.dump(self.to_dict(), f, indent=indent)

            return file_path
        except Exception as e:
            raise ValidationError(f"Failed to save to file {file_path}: {str(e)}")

    def validate_against_schema(self, validator: Optional[SchemaValidator] = None) -> List[str]:
        """
        Validate the model against the JSON schema.

        Args:
            validator: Schema validator to use. If None, creates a new one.

        Returns:
            A list of validation error messages, if any.
        """
        if validator is None:
            validator = SchemaValidator()

        return validator.validate(self.to_dict())

    def deep_copy(self) -> "BaseModel":
        """
        Create a deep copy of the model.

        Returns:
            A new model instance with the same data.
        """
        return self.__class__.from_dict(copy.deepcopy(self.to_dict()))