"""HTTP routes for local hardware records and reference images."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi import Path as ApiPath
from fastapi.responses import FileResponse
from pydantic import BaseModel

from scan_hardware.config import Settings
from scan_hardware.models.item import Category, GalleryImage, Item, ItemInput
from scan_hardware.services.catalog import Catalog, IdentifierConflictError
from scan_hardware.services.image_store import ImageView, store_image
from scan_hardware.services.ocr import InvalidImageError

ItemId = Annotated[str, ApiPath(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
ImageName = Annotated[str, ApiPath(pattern=r"^[a-f0-9]{64}\.(jpg|png|webp)$")]


class SocketRelatedItem(BaseModel):
    """Compact hardware candidate sharing a reported socket."""

    id: str
    category: Category
    brand: str
    model: str
    image_url: str | None
    socket: str


class SocketRelatedResponse(BaseModel):
    """Paginated socket association, without a compatibility guarantee."""

    socket: str | None
    relation: str = "same_socket"
    total: int
    matches: list[SocketRelatedItem]
    note: str = "Same socket does not confirm chipset, BIOS, or generation support."


def register_catalog_routes(app: FastAPI, catalog: Catalog, config: Settings) -> None:
    """Attach catalog endpoints to the service application."""

    @app.put("/items/{item_id}", response_model=Item)
    def put_item(item_id: ItemId, item: ItemInput) -> Item:
        """Create or replace one hardware item idempotently."""
        try:
            return catalog.put_item(item_id, item)
        except IdentifierConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/specs/{item_id}", response_model=Item)
    def get_specs(item_id: ItemId) -> Item:
        """Fetch one registered hardware item with detailed specifications."""
        item = catalog.get_item(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")
        return item

    @app.get("/items/{item_id}/sources")
    def get_item_sources(item_id: ItemId) -> list[dict[str, Any]]:
        """Return original imported rows, including every source column."""
        if catalog.get_item(item_id) is None:
            raise HTTPException(status_code=404, detail="Item not found")
        return catalog.get_source_records(item_id)

    register_socket_routes(app, catalog)
    register_image_routes(app, catalog, config)


def register_socket_routes(app: FastAPI, catalog: Catalog) -> None:
    """Attach the bidirectional CPU and motherboard socket association."""

    @app.get("/specs/{item_id}/socket-related", response_model=SocketRelatedResponse)
    def get_socket_related(
        item_id: ItemId,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> SocketRelatedResponse:
        """List CPUs or motherboards sharing the item's reported socket."""
        item = catalog.get_item(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")
        if item.category not in {Category.CPU, Category.MOTHERBOARD}:
            raise HTTPException(status_code=422, detail="Item has no CPU socket relationship")
        specification = item.specifications.get("socket")
        socket = specification.value if specification is not None else None
        if not isinstance(socket, str):
            return SocketRelatedResponse(socket=None, total=0, matches=[])
        target = Category.CPU if item.category is Category.MOTHERBOARD else Category.MOTHERBOARD
        total, matches = catalog.list_socket_related(socket, target, limit=limit, offset=offset)
        return SocketRelatedResponse(
            socket=socket,
            total=total,
            matches=[
                SocketRelatedItem(
                    id=candidate.id,
                    category=candidate.category,
                    brand=candidate.brand,
                    model=candidate.model,
                    image_url=candidate.local_image_url
                    or (str(candidate.image_url) if candidate.image_url else None),
                    socket=socket,
                )
                for candidate in matches
            ],
        )


def register_image_routes(app: FastAPI, catalog: Catalog, config: Settings) -> None:
    """Attach image upload and download endpoints to the service."""

    @app.put("/items/{item_id}/image", response_model=Item)
    async def put_image(item_id: ItemId, image: Annotated[UploadFile, File()]) -> Item:
        """Attach an image to a registered item."""
        if catalog.get_item(item_id) is None:
            raise HTTPException(status_code=404, detail="Item not found")
        content = await image.read(config.max_upload_bytes + 1)
        await image.close()
        try:
            return store_image(
                content,
                config.image_dir,
                catalog,
                item_id,
                "front",
                True,
                config.max_upload_bytes,
                enforce_primary_quality=False,
            )
        except InvalidImageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/items/{item_id}/image", response_class=FileResponse)
    def get_image(item_id: ItemId) -> FileResponse:
        """Serve the current local catalog image."""
        digest = catalog.get_image_digest(item_id)
        if digest is None:
            raise HTTPException(status_code=404, detail="Image not found")
        path = config.image_dir / digest
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Image file not found")
        return FileResponse(path)

    register_gallery_routes(app, catalog, config)


def register_gallery_routes(app: FastAPI, catalog: Catalog, config: Settings) -> None:
    """Attach endpoints for multiple local views of the same product."""

    @app.put("/items/{item_id}/images/{view}", response_model=Item)
    async def put_gallery_image(
        item_id: ItemId,
        view: ImageView,
        image: Annotated[UploadFile, File()],
        primary: Annotated[bool | None, Query()] = None,
    ) -> Item:
        """Attach a product view; a front view becomes primary by default."""
        if catalog.get_item(item_id) is None:
            raise HTTPException(status_code=404, detail="Item not found")
        content = await image.read(config.max_upload_bytes + 1)
        await image.close()
        try:
            return store_image(
                content,
                config.image_dir,
                catalog,
                item_id,
                view,
                view == "front" if primary is None else primary,
                config.max_upload_bytes,
            )
        except InvalidImageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/items/{item_id}/images", response_model=list[GalleryImage])
    def get_gallery(item_id: ItemId) -> list[GalleryImage]:
        """List local product angles, or the current external reference."""
        item = catalog.get_item(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")
        images = [
            GalleryImage(
                url=f"/items/{item_id}/images/{entry['file_name']}",
                view=entry["view"],
                is_primary=bool(entry["is_primary"]),
                source="local",
                width=entry["width"],
                height=entry["height"],
            )
            for entry in catalog.list_images(item_id)
        ]
        if item.image_url and not any(image.is_primary for image in images):
            images.insert(
                0,
                GalleryImage(
                    url=str(item.image_url), view="other", is_primary=True, source="external"
                ),
            )
        return images

    register_gallery_download_route(app, catalog, config)


def register_gallery_download_route(app: FastAPI, catalog: Catalog, config: Settings) -> None:
    """Expose immutable local gallery bytes with item ownership checks."""

    @app.get("/items/{item_id}/images/{file_name}", response_class=FileResponse)
    def get_gallery_image(item_id: ItemId, file_name: ImageName) -> FileResponse:
        """Serve one image only when it belongs to the requested product."""
        try:
            belongs_to_item = catalog.has_image(item_id, file_name)
        except KeyError:
            belongs_to_item = False
        if not belongs_to_item:
            raise HTTPException(status_code=404, detail="Image not found")
        path = config.image_dir / file_name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Image file not found")
        return FileResponse(path)
