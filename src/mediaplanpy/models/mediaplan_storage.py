"""
Integration of MediaPlan models with storage functionality.

This module enhances the MediaPlan model with methods for saving to
and loading from storage backends.
"""

import os
import logging
import os
from typing import Dict, Any, Optional, Union, Type, ClassVar

from mediaplanpy.exceptions import StorageError, FileReadError, FileWriteError
from mediaplanpy.models.mediaplan import MediaPlan
from mediaplanpy.storage import (
    read_mediaplan as storage_read_mediaplan,
    write_mediaplan as storage_write_mediaplan,
    get_format_handler_instance
)
from mediaplanpy.workspace import WorkspaceManager

logger = logging.getLogger("mediaplanpy.models.mediaplan_storage")

# Define constants
MEDIAPLANS_SUBDIR = "mediaplans"

# Add storage-related methods to MediaPlan class
import uuid
from datetime import datetime


def save(self, workspace_manager: WorkspaceManager, path: Optional[str] = None,
         format_name: Optional[str] = None, overwrite: bool = False,
         include_parquet: bool = True, **format_options) -> str:
    """
    Save the media plan to a storage location.

    Args:
        workspace_manager: The WorkspaceManager instance.
        path: The path where the media plan should be saved. If None or empty,
              a default path is generated based on the media plan ID.
        format_name: Optional format name to use. If not specified, inferred from path
                    or defaults to "json".
        overwrite: If False (default), saves with a new media plan ID. If True,
                  preserves the existing media plan ID.
        include_parquet: If True (default), also saves a Parquet file for v1.0.0+ schemas.
        **format_options: Additional format-specific options.

    Returns:
        The path where the media plan was saved.

    Raises:
        StorageError: If the media plan cannot be saved.
    """
    # Check if workspace is loaded
    if not workspace_manager.is_loaded:
        workspace_manager.load()

    # Get resolved workspace config
    workspace_config = workspace_manager.get_resolved_config()

    # Handle media plan ID based on overwrite parameter
    if not overwrite:
        # Generate a new media plan ID
        new_id = f"mediaplan_{uuid.uuid4().hex[:8]}"
        self.meta.id = new_id
        logger.info(f"Generated new media plan ID: {new_id}")

    # Update created_at timestamp regardless of overwrite value
    self.meta.created_at = datetime.now()

    # Generate default path if not provided
    if not path:
        # Default format is json if not specified
        default_format = format_name or "json"
        # Get format extension (remove leading dot if present)
        format_handler = get_format_handler_instance(default_format)
        extension = format_handler.get_file_extension()
        if extension.startswith('.'):
            extension = extension[1:]

        # Use media plan ID as filename (changed from campaign ID)
        mediaplan_id = self.meta.id
        # Sanitize media plan ID for use as a filename
        mediaplan_id = mediaplan_id.replace('/', '_').replace('\\', '_')

        # Generate path: mediaplans/mediaplan_id.extension
        path = os.path.join(MEDIAPLANS_SUBDIR, f"{mediaplan_id}.{extension}")

    # If path doesn't already include the mediaplans subdirectory, add it
    if not path.startswith(MEDIAPLANS_SUBDIR):
        path = os.path.join(MEDIAPLANS_SUBDIR, os.path.basename(path))

    # Convert model to dictionary
    data = self.to_dict()

    # Get storage backend to create subdirectory
    try:
        from mediaplanpy.storage import get_storage_backend
        storage_backend = get_storage_backend(workspace_config)

        # Create mediaplans subdirectory if needed
        if hasattr(storage_backend, 'create_directory'):
            storage_backend.create_directory(MEDIAPLANS_SUBDIR)
    except Exception as e:
        logger.warning(f"Could not ensure mediaplans directory exists: {e}")

    # Write to storage
    storage_write_mediaplan(workspace_config, data, path, format_name, **format_options)

    logger.info(f"Media plan saved to {path}")

    # Also save Parquet file for v1.0.0+ schemas
    if include_parquet and self._should_save_parquet():
        parquet_path = self._get_parquet_path(path)

        # Create separate options for Parquet
        parquet_options = {k: v for k, v in format_options.items()
                           if k in ['compression']}

        # Write Parquet file
        storage_write_mediaplan(
            workspace_config, data, parquet_path,
            format_name="parquet", **parquet_options
        )
        logger.info(f"Also saved Parquet file: {parquet_path}")

    # Return the path where the media plan was saved
    return path


def _should_save_parquet(self) -> bool:
    """
    Check if Parquet should be saved (v1.0.0+).

    Returns:
        True if the schema version is v1.0.0 or higher.
    """
    version = self.meta.schema_version
    if not version:
        return False

    # Simple version comparison for v1.0.0+
    # This assumes version format vX.Y.Z
    if version.startswith('v'):
        try:
            major = int(version.split('.')[0][1:])
            return major >= 1
        except (ValueError, IndexError):
            return False

    return False


def _get_parquet_path(self, json_path: str) -> str:
    """
    Get Parquet path from JSON path.

    Args:
        json_path: The JSON file path.

    Returns:
        The corresponding Parquet file path.
    """
    base, _ = os.path.splitext(json_path)
    return f"{base}.parquet"


def load(cls, workspace_manager: WorkspaceManager, path: Optional[str] = None,
         media_plan_id: Optional[str] = None, campaign_id: Optional[str] = None,
         format_name: Optional[str] = None) -> 'MediaPlan':
    """
    Load a media plan from a storage location.

    Args:
        workspace_manager: The WorkspaceManager instance.
        path: The path to the media plan file. Required if neither media_plan_id nor campaign_id is provided.
        media_plan_id: The media plan ID to load. If provided and path is None, will try to
                       load from a default path based on media_plan_id. Takes precedence over campaign_id.
        campaign_id: The campaign ID to load (deprecated, kept for backward compatibility).
                     If provided and path/media_plan_id are None, will try to load from
                     a default path based on campaign_id.
        format_name: Optional format name to use. If not specified, inferred from path
                     or defaults to "json".

    Returns:
        A MediaPlan instance.

    Raises:
        StorageError: If the media plan cannot be loaded.
        ValueError: If neither path, media_plan_id, nor campaign_id is provided.
    """
    # Check if workspace is loaded
    if not workspace_manager.is_loaded:
        workspace_manager.load()

    # Get resolved workspace config
    workspace_config = workspace_manager.get_resolved_config()

    # Generate default path if not provided but media_plan_id or campaign_id is
    if not path:
        if media_plan_id:
            # Use media plan ID (new preferred approach)
            # Default format is json if not specified
            default_format = format_name or "json"
            # Get format extension
            format_handler = get_format_handler_instance(default_format)
            extension = format_handler.get_file_extension()
            if extension.startswith('.'):
                extension = extension[1:]

            # Sanitize media plan ID for use as a filename
            safe_media_plan_id = media_plan_id.replace('/', '_').replace('\\', '_')

            # Generate path: mediaplans/media_plan_id.extension
            path = os.path.join(MEDIAPLANS_SUBDIR, f"{safe_media_plan_id}.{extension}")

            logger.info(f"Loading media plan by ID: {media_plan_id}")

        elif campaign_id:
            # Use campaign ID (backward compatibility)
            logger.warning("Loading by campaign_id is deprecated. Consider using media_plan_id instead.")

            # Default format is json if not specified
            default_format = format_name or "json"
            # Get format extension
            format_handler = get_format_handler_instance(default_format)
            extension = format_handler.get_file_extension()
            if extension.startswith('.'):
                extension = extension[1:]

            # Sanitize campaign ID for use as a filename
            safe_campaign_id = campaign_id.replace('/', '_').replace('\\', '_')

            # Generate path: mediaplans/campaign_id.extension (old approach)
            path = os.path.join(MEDIAPLANS_SUBDIR, f"{safe_campaign_id}.{extension}")

            logger.info(f"Loading media plan by campaign ID (deprecated): {campaign_id}")

    # Validate we have a path
    if not path:
        raise ValueError("Either path, media_plan_id, or campaign_id must be provided")

    # If path doesn't already include the mediaplans subdirectory, try both locations
    if not path.startswith(MEDIAPLANS_SUBDIR):
        # First try in the mediaplans subdirectory
        mediaplans_path = os.path.join(MEDIAPLANS_SUBDIR, os.path.basename(path))

        try:
            # Get storage backend to check if file exists in new location
            from mediaplanpy.storage import get_storage_backend
            storage_backend = get_storage_backend(workspace_config)

            if storage_backend.exists(mediaplans_path):
                path = mediaplans_path
            # Otherwise, keep the original path (for backward compatibility)
        except Exception as e:
            logger.warning(f"Error checking mediaplans subdirectory: {e}")

    # Read from storage
    try:
        data = storage_read_mediaplan(workspace_config, path, format_name)

        # Create MediaPlan instance from dictionary
        media_plan = cls.from_dict(data)

        logger.info(f"Media plan loaded from {path}")
        return media_plan
    except FileReadError:
        # Try legacy path as fallback if path was already modified
        if path.startswith(MEDIAPLANS_SUBDIR):
            legacy_path = os.path.basename(path)
            try:
                data = storage_read_mediaplan(workspace_config, legacy_path, format_name)

                # Create MediaPlan instance from dictionary
                media_plan = cls.from_dict(data)

                logger.warning(f"Media plan loaded from legacy path {legacy_path}. Future saves will use new path structure.")
                return media_plan
            except Exception:
                # If legacy path also failed, re-raise original error
                pass

        # If all attempts failed, raise appropriate error
        raise StorageError(f"Failed to read media plan from {path}")

# Patch methods into MediaPlan class
MediaPlan.save = save
MediaPlan.load = classmethod(load)
MediaPlan._should_save_parquet = _should_save_parquet
MediaPlan._get_parquet_path = _get_parquet_path