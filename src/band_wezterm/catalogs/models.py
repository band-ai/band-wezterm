"""Provider-neutral model catalog values."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from band_wezterm.harnesses.models import (
    TUNING_DEFAULT_OPTION_ID,
    TuningDimension,
    TuningDimensionId,
    TuningOption,
)

_DEFAULT_OPTION = TuningOption(
    id=TUNING_DEFAULT_OPTION_ID,
    label="Adapter default",
)


class ModelCatalogEntry(BaseModel):
    """One selectable model and the efforts that model accepts."""

    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    description: str | None = None
    efforts: tuple[TuningOption, ...] = ()

    @property
    def option(self) -> TuningOption:
        return TuningOption(
            id=self.id,
            label=self.label,
            description=self.description,
        )


class HarnessCatalog(BaseModel):
    """Live tuning choices for one harness."""

    model_config = ConfigDict(frozen=True)

    models: tuple[ModelCatalogEntry, ...]
    default_model_id: str | None = None

    def dimension(
        self,
        fallback: TuningDimension,
        *,
        selected_model: str | None,
    ) -> TuningDimension:
        match fallback.id:
            case TuningDimensionId.MODEL:
                options = (_DEFAULT_OPTION, *(model.option for model in self.models))
            case TuningDimensionId.REASONING:
                model = self._selected_model(selected_model)
                options = (
                    (_DEFAULT_OPTION, *model.efforts)
                    if model is not None
                    else (_DEFAULT_OPTION,)
                )
        return fallback.model_copy(update={"options": options})

    def _selected_model(self, selected_model: str | None) -> ModelCatalogEntry | None:
        model_id = selected_model or self.default_model_id
        return next((model for model in self.models if model.id == model_id), None)
