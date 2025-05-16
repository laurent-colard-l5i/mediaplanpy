"""
Local file storage backend for mediaplanpy.

This module provides a storage backend for storing media plans
on the local filesystem.
"""

import os
import logging
import shutil
import glob
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, BinaryIO, TextIO

from mediaplanpy.exceptions import StorageError, FileReadError, FileWriteError
from mediaplanpy.storage.base import StorageBackend

logger = logging.getLogger("mediaplanpy.storage.local")


class LocalStorageBackend(StorageBackend):
    """
    Storage backend for local filesystem.

    Reads and writes media plans to the local filesystem.
    """

    def __init__(self, workspace_config: Dict[str, Any]):
        """
        Initialize the local storage backend.

        Args:
            workspace_config: The resolved workspace configuration dictionary.
        """
        super().__init__(workspace_config)

        # Extract local storage configuration
        storage_config = workspace_config.get('storage', {})
        if storage_config.get('mode') != 'local':
            raise StorageError("Workspace not configured for local storage")

        local_config = storage_config.get('local', {})

        # Get base path
        self.base_path = local_config.get('base_path')
        if not self.base_path:
            raise StorageError("No base_path specified for local storage")

        # Resolve to absolute path
        self.base_path = os.path.abspath(os.path.expanduser(self.base_path))

        # Create directory if it doesn't exist and configuration allows it
        create_if_missing = local_config.get('create_if_missing', True)
        if create_if_missing and not os.path.exists(self.base_path):
            try:
                os.makedirs(self.base_path, exist_ok=True)
                logger.info(f"Created base directory for local storage: {self.base_path}")
            except Exception as e:
                raise StorageError(f"Failed to create base directory {self.base_path}: {e}")

        # Validate that the directory exists and is writable
        if not os.path.exists(self.base_path):
            raise StorageError(f"Local storage base path does not exist: {self.base_path}")

        if not os.path.isdir(self.base_path):
            raise StorageError(f"Local storage base path is not a directory: {self.base_path}")

        if not os.access(self.base_path, os.W_OK):
            raise StorageError(f"Local storage base path is not writable: {self.base_path}")

        logger.debug(f"Initialized local storage backend with base path: {self.base_path}")

    def resolve_path(self, path: str) -> str:
        """
        Resolve a path relative to the base path.

        Args:
            path: The path to resolve.

        Returns:
            The absolute path.
        """
        # If path is already absolute, return it
        if os.path.isabs(path):
            return path

        # Otherwise, join with base path
        return os.path.join(self.base_path, path)

    def join_path(self, *parts: str) -> str:
        """
        Join path components.

        Args:
            *parts: Path components to join.

        Returns:
            The joined path.
        """
        return os.path.join(*parts)

    def directory_exists(self, path: str) -> bool:
        """
        Check if a directory exists at the specified path.

        Args:
            path: The directory path to check.

        Returns:
            True if the directory exists, False otherwise.
        """
        full_path = self.resolve_path(path)
        return os.path.exists(full_path) and os.path.isdir(full_path)

    def list_directories(self, path: str = "") -> List[str]:
        """
        List subdirectories at the specified path.

        Args:
            path: The path to list directories from. If empty, lists from base path.

        Returns:
            A list of directory paths relative to the base path.
        """
        full_path = self.resolve_path(path)

        try:
            if not os.path.exists(full_path):
                return []

            if not os.path.isdir(full_path):
                raise StorageError(f"Path is not a directory: {full_path}")

            # List all directories
            directories = [
                os.path.join(path, d) for d in os.listdir(full_path)
                if os.path.isdir(os.path.join(full_path, d))
            ]

            # Normalize paths to use forward slashes for consistency
            normalized_dirs = [d.replace('\\', '/') for d in directories]

            return normalized_dirs
        except Exception as e:
            if not isinstance(e, StorageError):
                logger.error(f"Failed to list directories in {full_path}: {e}")
            return []

    def create_directory(self, path: str) -> None:
        """
        Create a directory at the specified path if it doesn't exist.

        Args:
            path: The path to the directory to create.

        Raises:
            StorageError: If the directory cannot be created.
        """
        try:
            # Resolve the path relative to base path
            full_path = self.resolve_path(path)

            # Create directory if it doesn't exist
            if not os.path.exists(full_path):
                os.makedirs(full_path, exist_ok=True)
                logger.debug(f"Created directory: {full_path}")
            elif not os.path.isdir(full_path):
                raise StorageError(f"Path exists but is not a directory: {full_path}")

        except Exception as e:
            if not isinstance(e, StorageError):
                raise StorageError(f"Failed to create directory {path}: {e}")
            raise

    def exists(self, path: str) -> bool:
        """
        Check if a file exists at the specified path.

        Args:
            path: The path to check.

        Returns:
            True if the file exists, False otherwise.
        """
        full_path = self.resolve_path(path)
        return os.path.exists(full_path) and os.path.isfile(full_path)

    def read_file(self, path: str, binary: bool = False) -> Union[str, bytes]:
        """
        Read a file from the local filesystem.

        Args:
            path: The path to the file.
            binary: If True, read the file in binary mode.

        Returns:
            The contents of the file, either as a string or as bytes.

        Raises:
            FileReadError: If the file cannot be read.
        """
        full_path = self.resolve_path(path)

        try:
            mode = 'rb' if binary else 'r'
            encoding = None if binary else 'utf-8'

            with open(full_path, mode=mode, encoding=encoding) as f:
                return f.read()
        except Exception as e:
            raise FileReadError(f"Failed to read file {full_path}: {e}")

    def write_file(self, path: str, content: Union[str, bytes]) -> None:
        """
        Write content to a file on the local filesystem.

        Args:
            path: The path where the file should be written.
            content: The content to write, either as a string or as bytes.

        Raises:
            FileWriteError: If the file cannot be written.
        """
        full_path = self.resolve_path(path)

        # Create directory if it doesn't exist
        directory = os.path.dirname(full_path)
        if directory and not os.path.exists(directory):
            try:
                os.makedirs(directory, exist_ok=True)
            except Exception as e:
                raise FileWriteError(f"Failed to create directory {directory}: {e}")

        try:
            # Determine mode based on content type
            mode = 'wb' if isinstance(content, bytes) else 'w'
            encoding = None if isinstance(content, bytes) else 'utf-8'

            with open(full_path, mode=mode, encoding=encoding) as f:
                f.write(content)
        except Exception as e:
            raise FileWriteError(f"Failed to write file {full_path}: {e}")

    def list_files(self, path: str, pattern: Optional[str] = None) -> List[str]:
        """
        List files in a directory on the local filesystem.

        Args:
            path: The directory path to list files from.
            pattern: Optional glob pattern to filter files.

        Returns:
            A list of file paths relative to the base path.

        Raises:
            StorageError: If the directory cannot be listed.
        """
        full_path = self.resolve_path(path)

        try:
            # Ensure path exists and is a directory
            if not os.path.exists(full_path):
                return []

            if not os.path.isdir(full_path):
                raise StorageError(f"Path is not a directory: {full_path}")

            # Apply glob pattern if provided
            if pattern:
                search_pattern = os.path.join(full_path, pattern)
                files = glob.glob(search_pattern)
            else:
                # Otherwise, list all files (not directories)
                files = [
                    os.path.join(full_path, f)
                    for f in os.listdir(full_path)
                    if os.path.isfile(os.path.join(full_path, f))
                ]

            # Convert back to paths relative to base path
            base_path_len = len(self.base_path) + 1  # +1 for trailing slash
            result = []
            for f in files:
                if f.startswith(self.base_path):
                    # Make sure we use forward slashes for consistency across platforms
                    rel_path = f[base_path_len:]
                    rel_path = rel_path.replace('\\', '/')
                    result.append(rel_path)
                else:
                    result.append(f)
            return result
        except Exception as e:
            raise StorageError(f"Failed to list files in {full_path}: {e}")

    def delete_file(self, path: str) -> None:
        """
        Delete a file on the local filesystem.

        Args:
            path: The path to the file to delete.

        Raises:
            StorageError: If the file cannot be deleted.
        """
        full_path = self.resolve_path(path)

        try:
            if os.path.exists(full_path) and os.path.isfile(full_path):
                os.remove(full_path)
        except Exception as e:
            raise StorageError(f"Failed to delete file {full_path}: {e}")

    def get_file_info(self, path: str) -> Dict[str, Any]:
        """
        Get information about a file on the local filesystem.

        Args:
            path: The path to the file.

        Returns:
            A dictionary with file information (size, modified date, etc).

        Raises:
            StorageError: If the file information cannot be retrieved.
        """
        full_path = self.resolve_path(path)

        try:
            if not os.path.exists(full_path):
                raise StorageError(f"File does not exist: {full_path}")

            stat_info = os.stat(full_path)

            return {
                'path': path,
                'full_path': full_path,
                'size': stat_info.st_size,
                'created': datetime.datetime.fromtimestamp(stat_info.st_ctime),
                'modified': datetime.datetime.fromtimestamp(stat_info.st_mtime),
                'accessed': datetime.datetime.fromtimestamp(stat_info.st_atime),
                'is_directory': os.path.isdir(full_path)
            }
        except Exception as e:
            raise StorageError(f"Failed to get file info for {full_path}: {e}")

    def open_file(self, path: str, mode: str = 'r') -> Union[TextIO, BinaryIO]:
        """
        Open a file on the local filesystem and return a file-like object.

        Args:
            path: The path to the file.
            mode: The mode to open the file in ('r', 'w', 'rb', 'wb', etc).

        Returns:
            A file-like object.

        Raises:
            StorageError: If the file cannot be opened.
        """
        full_path = self.resolve_path(path)

        # Create directory if it doesn't exist and we're opening for writing
        if 'w' in mode or 'a' in mode:
            directory = os.path.dirname(full_path)
            if directory and not os.path.exists(directory):
                try:
                    os.makedirs(directory, exist_ok=True)
                except Exception as e:
                    raise StorageError(f"Failed to create directory {directory}: {e}")

        try:
            # Determine encoding based on mode
            binary_mode = 'b' in mode
            encoding = None if binary_mode else 'utf-8'

            return open(full_path, mode=mode, encoding=encoding)
        except Exception as e:
            raise StorageError(f"Failed to open file {full_path}: {e}")