from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class LocalFile:
    name: str
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class FileInfo:
    name: str
    size: int
    sha256: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileInfo":
        return cls(
            name=str(data.get("name", "")),
            size=int(data.get("size", 0)),
            sha256=str(data.get("sha256", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "size": self.size,
            "sha256": self.sha256,
        }


@dataclass(frozen=True)
class PeerInfo:
    ip: str
    port: int
    chunks_available: Optional[list[int]]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PeerInfo":
        chunks = data.get("chunks_available")
        return cls(
            ip=str(data.get("ip", "")),
            port=int(data.get("port", 0)),
            chunks_available=list(chunks) if chunks is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ip": self.ip,
            "port": self.port,
            "chunks_available": self.chunks_available,
        }


@dataclass(frozen=True)
class SearchResult:
    file_info: FileInfo
    peers: list[PeerInfo]

    @classmethod
    def from_tracker_response(cls, response: dict[str, Any]) -> "SearchResult":
        return cls(
            file_info=FileInfo.from_dict(response.get("file_info", {})),
            peers=[
                PeerInfo.from_dict(peer)
                for peer in response.get("peers", [])
            ],
        )


@dataclass(frozen=True)
class DownloadProgress:
    filename: str
    completed_chunks: int
    total_chunks: int
    percent: int
    active_peers: int
    speed_bytes_per_second: float
    status: str = "downloading"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DownloadProgress":
        return cls(
            filename=str(data.get("filename", "")),
            completed_chunks=int(data.get("completed_chunks", 0)),
            total_chunks=int(data.get("total_chunks", 0)),
            percent=int(data.get("percent", 0)),
            active_peers=int(data.get("active_peers", 0)),
            speed_bytes_per_second=float(data.get("speed_bytes_per_second", 0.0)),
            status=str(data.get("status", "downloading")),
        )

