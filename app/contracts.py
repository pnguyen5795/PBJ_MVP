"""Provider-neutral JSON contracts shared by analyzers, planner, and renderer."""

SEGMENT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["segment_id", "start_seconds", "end_seconds", "transcript", "visual_description", "audio_description", "subjects", "actions", "shot_type", "camera_movement", "emotional_tone", "editorial_roles", "quality", "duplicate_group", "confidence"],
    "properties": {
        "segment_id": {"type": "string"}, "start_seconds": {"type": "number", "minimum": 0}, "end_seconds": {"type": "number", "minimum": 0},
        "transcript": {"type": "string"}, "visual_description": {"type": "string"}, "audio_description": {"type": "string"},
        "subjects": {"type": "array", "items": {"type": "string"}}, "actions": {"type": "array", "items": {"type": "string"}},
        "shot_type": {"type": "string"}, "camera_movement": {"type": "string"}, "emotional_tone": {"type": "string"},
        "editorial_roles": {"type": "array", "items": {"type": "string"}},
        "quality": {"type": "string", "enum": ["strong", "usable", "weak", "unusable", "uncertain"]},
        "duplicate_group": {"type": ["string", "null"]}, "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}

OBSERVATION_KEYS = ["opening", "pacing", "shot_pattern", "cut_pattern", "reframing", "b_roll", "transitions", "speed", "audio_continuity", "ending", "other"]
VIDEO_ANALYSIS_JSON_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["summary", "content_type", "speakers", "story_beats", "segments", "editing_observations", "uncertainties"],
    "properties": {
        "summary": {"type": "string"}, "content_type": {"type": "string"},
        "speakers": {"type": "array", "items": {"type": "string"}}, "story_beats": {"type": "array", "items": {"type": "string"}},
        "segments": {"type": "array", "items": SEGMENT_SCHEMA},
        "editing_observations": {"type": "object", "additionalProperties": False, "required": OBSERVATION_KEYS, "properties": {key: {"type": "array", "items": {"type": "string"}} for key in OBSERVATION_KEYS}},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
}

ANALYSIS_SCHEMA = {"schema_version": "1.0", "required": ["file_id", "provider", "model", "duration_seconds", "analysis"], "analysis": VIDEO_ANALYSIS_JSON_SCHEMA}

RECIPE_EVIDENCE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["reference_file_id", "segment_id", "start_seconds", "end_seconds", "observation"],
    "properties": {
        "reference_file_id": {"type": "string"},
        "segment_id": {"type": "string"},
        "start_seconds": {"type": "number", "minimum": 0},
        "end_seconds": {"type": "number", "minimum": 0},
        "observation": {"type": "string"},
    },
}

RECIPE_RULE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["rule_id", "category", "name", "description", "instruction", "classification", "condition", "exceptions", "renderer_support", "supporting_reference_count", "total_reference_count", "confidence", "evidence", "conflicts"],
    "properties": {
        "rule_id": {"type": "string"},
        "category": {"type": "string", "enum": ["structure", "pacing", "selection", "visual", "audio", "ending", "other"]},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "instruction": {"type": "string"},
        "classification": {"type": "string", "enum": ["core", "common", "conditional", "optional", "one_off"]},
        "condition": {"type": "string"},
        "exceptions": {"type": "array", "items": {"type": "string"}},
        "renderer_support": {"type": "string", "enum": ["supported", "partial", "unsupported"]},
        "supporting_reference_count": {"type": "integer", "minimum": 0},
        "total_reference_count": {"type": "integer", "minimum": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": {"type": "array", "items": RECIPE_EVIDENCE_SCHEMA},
        "conflicts": {"type": "array", "items": {"type": "string"}},
    },
}

RECIPE_SYNTHESIS_JSON_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["summary", "creative_principles", "structure_summary", "compatibility", "avoid", "rules", "unsupported_observations", "uncertainties"],
    "properties": {
        "summary": {"type": "string"},
        "creative_principles": {"type": "array", "items": {"type": "string"}},
        "structure_summary": {"type": "string"},
        "compatibility": {"type": "array", "items": {"type": "string"}},
        "avoid": {"type": "array", "items": {"type": "string"}},
        "rules": {"type": "array", "items": RECIPE_RULE_SCHEMA},
        "unsupported_observations": {"type": "array", "items": {"type": "string"}},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
}

# Compatibility name retained while the style-oriented routes are migrated.
STYLE_SYNTHESIS_JSON_SCHEMA = RECIPE_SYNTHESIS_JSON_SCHEMA

STYLE_PROFILE_SCHEMA = {
    "schema_version": "2.0",
    "required": ["style_id", "status", "recipe", "recipe_version", "recipe_status", "reference_files"],
}

EDIT_PLAN_SCHEMA = {
    "schema_version": "1.0", "required": ["project_id", "style_id", "provider", "target", "video_segments", "audio_segments", "warnings"],
    "target": {"width": 1080, "height": 1920, "min_duration_seconds": 15, "max_duration_seconds": 180, "video_codec": "h264", "audio_codec": "aac"},
    "allowed_operations": ["trim", "reorder", "hard_cut", "crossfade", "static_crop", "punch_in", "simple_zoom", "speed_change", "b_roll_overlay", "audio_normalization", "noise_reduction", "fit_to_frame", "blurred_source_background"],
}

CANDIDATE_SELECTION_JSON_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["story_strategy", "selected_candidates", "warnings"],
    "properties": {
        "story_strategy": {"type": "string"},
        "selected_candidates": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["candidate_id", "intended_role", "reason", "priority"],
            "properties": {"candidate_id": {"type": "string"}, "intended_role": {"type": "string"}, "reason": {"type": "string"}, "priority": {"type": "integer", "minimum": 1}},
        }},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}

VIDEO_PLAN_SEGMENT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["source_file_id", "source_start", "source_end", "timeline_start", "timeline_end", "crop_mode", "focal_x", "focal_y", "zoom_start", "zoom_end", "speed", "transition", "transition_duration", "style_reasons"],
    "properties": {
        "source_file_id": {"type": "string"}, "source_start": {"type": "number", "minimum": 0}, "source_end": {"type": "number", "minimum": 0},
        "timeline_start": {"type": "number", "minimum": 0}, "timeline_end": {"type": "number", "minimum": 0},
        "crop_mode": {"type": "string", "enum": ["center_crop", "focal_crop", "fit", "blurred_background"]},
        "focal_x": {"type": "number", "minimum": 0, "maximum": 1}, "focal_y": {"type": "number", "minimum": 0, "maximum": 1},
        "zoom_start": {"type": "number", "minimum": 1, "maximum": 1.5}, "zoom_end": {"type": "number", "minimum": 1, "maximum": 1.5}, "speed": {"type": "number", "minimum": 0.5, "maximum": 2},
        "transition": {"type": "string", "enum": ["cut", "crossfade"]},
        "transition_duration": {"type": "number", "minimum": 0, "maximum": 1},
        "style_reasons": {"type": "array", "items": {"type": "string"}},
    },
}

AUDIO_PLAN_SEGMENT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["source_file_id", "source_start", "source_end", "timeline_start", "timeline_end", "speed", "normalize", "noise_reduction"],
    "properties": {
        "source_file_id": {"type": "string"}, "source_start": {"type": "number", "minimum": 0}, "source_end": {"type": "number", "minimum": 0},
        "timeline_start": {"type": "number", "minimum": 0}, "timeline_end": {"type": "number", "minimum": 0},
        "speed": {"type": "number", "minimum": 0.5, "maximum": 2}, "normalize": {"type": "boolean"}, "noise_reduction": {"type": "boolean"},
    },
}

ROUGH_CUT_PLAN_JSON_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "creative_summary", "target_duration_seconds", "video_segments", "audio_segments", "warnings"],
    "properties": {
        "title": {"type": "string"}, "creative_summary": {"type": "string"},
        "target_duration_seconds": {"type": "number", "minimum": 15, "maximum": 180},
        "video_segments": {"type": "array", "minItems": 1, "items": VIDEO_PLAN_SEGMENT_SCHEMA},
        "audio_segments": {"type": "array", "minItems": 1, "items": AUDIO_PLAN_SEGMENT_SCHEMA},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
}
