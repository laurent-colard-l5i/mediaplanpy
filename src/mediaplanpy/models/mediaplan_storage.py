"""
Updated MediaPlan storage integration with database support.

This module updates the MediaPlan storage methods to automatically save
media plans to PostgreSQL database when configured.
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
         include_parquet: bool = True, include_database: bool = True,
         **format_options) -> str:
    """
    Save the media plan to a storage location with optional database sync.

    Args:
        workspace_manager: The WorkspaceManager instance.
        path: The path where the media plan should be saved. If None or empty,
              a default path is generated based on the media plan ID.
        format_name: Optional format name to use. If not specified, inferred from path
                    or defaults to "json".
        overwrite: If False (default), saves with a new media plan ID. If True,
                  preserves the existing media plan ID.
        include_parquet: If True (default), also saves a Parquet file for v1.0.0+ schemas.
        include_database: If True (default), also saves to database if configured.
        **format_options: Additional format-specific options.

    Returns:
        The path where the media plan was saved.

    Raises:
        StorageError: If the media plan cannot be saved.
        WorkspaceInactiveError: If the workspace is inactive.
    """
    # Check if workspace is active
    workspace_manager.check_workspace_active("media plan save")

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

    # Save to database if configured and enabled
    if include_database:
        try:
            db_saved = self.save_to_database(workspace_manager, overwrite=overwrite)
            if db_saved:
                logger.info(f"Media plan {self.meta.id} synchronized to database")
            else:
                logger.debug(f"Database sync skipped for media plan {self.meta.id}")
        except Exception as e:
            # Database errors should not prevent file save
            logger.warning(f"Database sync failed for media plan {self.meta.id}: {e}")

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


def delete(self, workspace_manager: 'WorkspaceManager',
           dry_run: bool = False, include_database: bool = True) -> Dict[str, Any]:
    """
    Delete the media plan files from workspace storage and optionally from database.

    This method removes both JSON and Parquet files associated with this media plan
    from the workspace storage. The files are located in the 'mediaplans' subdirectory.
    If database integration is enabled, it will also remove database records.

    Args:
        workspace_manager: The WorkspaceManager instance.
        dry_run: If True, shows what would be deleted without actually deleting files.
        include_database: If True, also delete from database if configured.

    Returns:
        Dictionary containing:
        - deleted_files: List of files that were (or would be) deleted
        - errors: List of any errors encountered
        - mediaplan_id: The media plan ID
        - dry_run: Whether this was a dry run
        - files_found: Total number of files found
        - files_deleted: Total number of files successfully deleted
        - database_deleted: Whether database records were deleted
        - database_rows_deleted: Number of database rows deleted

    Raises:
        WorkspaceError: If no configuration is loaded.
        WorkspaceInactiveError: If the workspace is inactive.
        StorageError: If deletion fails due to storage backend issues.
    """
    # Check if workspace is active (deletion is a restricted operation)
    workspace_manager.check_workspace_active("media plan deletion")

    # Check if workspace is loaded
    if not workspace_manager.is_loaded:
        workspace_manager.load()

    # Get resolved workspace config and storage backend
    workspace_config = workspace_manager.get_resolved_config()

    try:
        from mediaplanpy.storage import get_storage_backend
        storage_backend = get_storage_backend(workspace_config)
    except Exception as e:
        raise StorageError(f"Failed to get storage backend: {e}")

    # Initialize result dictionary
    result = {
        "deleted_files": [],
        "errors": [],
        "mediaplan_id": self.meta.id,
        "dry_run": dry_run,
        "files_found": 0,
        "files_deleted": 0,
        "database_deleted": False,
        "database_rows_deleted": 0
    }

    # Define file extensions to look for
    extensions = ["json", "parquet"]

    # Sanitize media plan ID for use as filename
    safe_mediaplan_id = self.meta.id.replace('/', '_').replace('\\', '_')

    for extension in extensions:
        # Construct the file path in mediaplans subdirectory
        file_path = os.path.join(MEDIAPLANS_SUBDIR, f"{safe_mediaplan_id}.{extension}")

        try:
            # Check if file exists
            if storage_backend.exists(file_path):
                result["files_found"] += 1

                if dry_run:
                    # For dry run, just add to the list without deleting
                    result["deleted_files"].append(file_path)
                    logger.info(f"[DRY RUN] Would delete: {file_path}")
                else:
                    # Actually delete the file
                    storage_backend.delete_file(file_path)
                    result["deleted_files"].append(file_path)
                    result["files_deleted"] += 1
                    logger.info(f"Deleted media plan file: {file_path}")
            else:
                logger.debug(f"File not found (skipping): {file_path}")

        except Exception as e:
            error_msg = f"Failed to delete {file_path}: {str(e)}"
            result["errors"].append(error_msg)
            logger.error(error_msg)

    # Handle database deletion if enabled
    if include_database:
        try:
            if self._should_save_to_database(workspace_manager):
                if dry_run:
                    logger.info(f"[DRY RUN] Would delete database records for media plan {self.meta.id}")
                    result["database_deleted"] = True  # Would be deleted
                else:
                    # Actually delete from database
                    from mediaplanpy.storage.database import PostgreSQLBackend
                    db_backend = PostgreSQLBackend(workspace_config)

                    workspace_id = workspace_manager.config.get('workspace_id', 'unknown')
                    deleted_rows = db_backend.delete_media_plan(self.meta.id, workspace_id)

                    result["database_deleted"] = True
                    result["database_rows_deleted"] = deleted_rows

                    logger.info(f"Deleted {deleted_rows} database records for media plan {self.meta.id}")
            else:
                logger.debug("Database deletion skipped - not configured or not applicable")

        except Exception as e:
            error_msg = f"Failed to delete database records: {str(e)}"
            result["errors"].append(error_msg)
            logger.error(error_msg)

    # Log summary
    if dry_run:
        logger.info(f"[DRY RUN] Media plan '{self.meta.id}': found {result['files_found']} files that would be deleted")
        if result["database_deleted"]:
            logger.info(f"[DRY RUN] Database records would also be deleted")
    else:
        logger.info(
            f"Media plan '{self.meta.id}': deleted {result['files_deleted']} of {result['files_found']} files found")
        if result["database_deleted"]:
            logger.info(f"Also deleted {result['database_rows_deleted']} database records")

    # Raise an error if there were any deletion failures (but not if files didn't exist)
    if result["errors"] and not dry_run:
        raise StorageError(
            f"Failed to delete some files for media plan '{self.meta.id}': {'; '.join(result['errors'])}")

    return result

# Patch methods into MediaPlan class
MediaPlan.save = save
MediaPlan.load = classmethod(load)
MediaPlan.delete = delete
MediaPlan._should_save_parquet = _should_save_parquet
MediaPlan._get_parquet_path = _get_parquet_path