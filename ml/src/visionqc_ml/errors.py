"""Domain errors raised by the ML workflow."""


class VisionQCError(Exception):
    """Base error with a stable machine-readable code."""

    code = "ml_error"


class DatasetIntegrityError(VisionQCError):
    """Dataset content or layout does not match its declared provenance."""

    code = "dataset_integrity_error"


class ManifestError(VisionQCError):
    """Manifest content is missing, inconsistent, or not reproducible."""

    code = "manifest_error"


class ModelPackageError(VisionQCError):
    """A model package is incomplete or fails integrity validation."""

    code = "model_package_error"


class InferenceInputError(VisionQCError):
    """An inference image is missing, corrupt, or outside configured limits."""

    code = "inference_input_error"


class ModelRuntimeUnavailable(VisionQCError):
    """The optional Anomalib/PyTorch runtime cannot be loaded."""

    code = "model_runtime_unavailable"

