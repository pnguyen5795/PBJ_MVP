VIDEO_ANALYSIS_PROMPT_VERSION = "video-analysis-v1"
STYLE_SYNTHESIS_PROMPT_VERSION = "recipe-synthesis-v1"
STYLE_REVISION_PROMPT_VERSION = "recipe-revision-v1"
CANDIDATE_SELECTION_PROMPT_VERSION = "candidate-selection-v2"
ROUGH_CUT_PLAN_PROMPT_VERSION = "rough-cut-plan-v2"
TIMELINE_REPAIR_PROMPT_VERSION = "timeline-repair-v1"
PLANNER_POLICY_VERSION = "planner-policy-v1"

VIDEO_ANALYSIS_PROMPT = """
Analyze this entire video as source material for a professional video editor.
Return detailed, timestamped observations in the supplied JSON schema. Treat
timestamps as seconds from the start of this original file. Create segment IDs
in chronological order (segment-001, segment-002, ...). Cover all meaningful
speech, actions, reactions, B-roll, pauses, repeated takes, and unusable ranges.

For every segment, distinguish what is visibly present from editorial inference.
Do not propose or invent external footage, music, imagery, voices, or facts.

Purpose: {purpose}

When the purpose is "style_reference", pay special attention to observable edit
patterns: hook construction, rhythm, cut frequency, shot-duration variation,
reordering, B-roll placement, punch-ins, zooms, reframing, transitions, speed,
audio continuity, pauses, emphasis, narrative movement, and ending behavior.
When the purpose is "raw_footage", identify the strongest available material and
its possible editorial role without deciding the final edit.
""".strip()

STYLE_SYNTHESIS_PROMPT = """
You are creating an evidence-backed internal video-editing recipe from analyses
of finished reference videos. Compare every reference rather than summarizing
them independently. Infer recurring, observable editing behavior while
preserving uncertainty. The recipe will guide later editing of different raw
footage, so express rules as concrete editorial instructions rather than vague
adjectives.

Every rule must cite real evidence using the exact reference file ID, segment ID,
and timestamp range found in the supplied analyses. Count distinct supporting
reference files, not the number of segments. Set total_reference_count to the
number of distinct reference files supplied. Never fabricate evidence. Record
counterexamples or conflicting observations in conflicts.

Classify each rule as core, common, conditional, optional, or one_off. A rule
cannot be core merely because it appears repeatedly inside one video. Use
conditional when the behavior depends on content or story context. Use one_off
when there is insufficient cross-reference support to generalize.

Use only evidence in the analyses. Never request generated video, images, audio,
music, voices, sound effects, or outside B-roll. Separate traits supported by the
current renderer from observed traits it cannot currently reproduce. The supported
operations are trimming, reordering, hard cuts, simple crossfades, static crops,
fixed punch-ins, simple zooms, speed changes, source B-roll over source dialogue,
audio normalization, basic noise reduction, fit-to-frame, and a blurred duplicate
background made from the same supplied footage.

Reference analyses:
{analyses_json}
""".strip()

STYLE_REVISION_PROMPT = """
Revise the evidence-backed editing recipe using the operator's feedback. Preserve
all source evidence, recurrence counts, conflicts, uncertainty, and valid rules
that the feedback does not change. Feedback may correct interpretation or change
emphasis, but it is not new reference-video evidence: do not increase evidence
counts or invent timestamps because of feedback. The revised recipe must not
request generated or outside media. Return the entire recipe in the schema.

Current recipe: {style_json}
Operator feedback: {feedback}
""".strip()

CANDIDATE_SELECTION_PROMPT = """
Select the best source moments for a first rough cut. Build a coherent story that
follows the approved internal editing recipe and the user's project prompt. Use only the
candidate IDs supplied. Prioritize complementary moments across files, remove
repeated takes, and select enough material to support the requested duration.
This is selection only; do not invent precise new timecodes or external media.

User prompt: {user_prompt}
Target duration: {target_seconds} seconds
Explicit requirements: {requirements_json}
Approved internal recipe: {style_json}
Content map: {content_map_json}
""".strip()

ROUGH_CUT_PLAN_PROMPT = """
Keep these instruction layers distinct. Follow this priority order when they conflict:
1. Non-negotiable product and media-safety rules in this prompt.
2. Technical constraints required by the edit-plan schema and renderer.
3. Explicit instructions for this specific project.
4. The approved internal recipe as the default editing approach.
5. Your editorial judgment for choices not decided above.

Project instructions may change story, emphasis, duration, and clip preferences,
but cannot override the supplied-media-only rule or technical validity. Recipe
rules guide unspecified choices and are not permission to invent unavailable material.
Learning signals are advisory evidence from prior revisions and approvals. Use them
when they fit the current project, but treat project-specific requests as local
preferences unless repeated signals support generalizing them.

Create the executable first-rough-cut plan from the selected source candidates.
Use only supplied source_file_id values and time ranges inside the candidates.
Video and audio timelines must each start at 0, be chronological, contain no gaps,
and end at target_duration_seconds. Audio segments cannot overlap. Video segments
may overlap only for a crossfade. A video segment may show B-roll
while an audio segment independently continues dialogue from another source.

The output must be a 1080x1920 vertical rough cut using original footage and
original audio only. Never add generated or outside media, captions, music, sound
effects, images, voices, or text. Use hard cuts by default; use a short crossfade
only when the approved style supports it. transition describes how a segment enters:
the first segment must use cut with transition_duration 0; every other cut must use
duration 0; and a crossfade must use a duration from 0.1 to 1 second and begin at
the previous segment's timeline_end minus transition_duration. Keep speed changes
subtle unless clearly supported by the style. focal_x and focal_y
are normalized static points from 0 (left/top) to 1 (right/bottom); use 0.5 for
the center. zoom_start and zoom_end can create a simple gradual zoom or a fixed
punch-in. For each video
segment, source duration divided by speed must equal timeline duration. The same
rule applies to audio. Use center_crop, fit, or blurred_background.

User prompt: {user_prompt}
Requested duration: {target_seconds} seconds
Explicit requirements that must be satisfied when matching footage exists: {requirements_json}
Approved internal recipe: {style_json}
Story selection: {selection_json}
Selected candidate details: {candidates_json}
""".strip()

TIMELINE_REPAIR_PROMPT = """
Repair the complete proposed edit plan using the deterministic validation error
and the real source constraints below. Preserve every valid editorial decision.
Use only listed source_file_id values. Keep every source range within 0 and its
real duration. Video and audio must each start at 0, remain continuous under the
transition rules, and end at the requested target when sufficient selected media
exists. Source duration divided by speed must equal timeline duration. Original
audio may come only from a listed source that has audio. Return the complete plan.

Project instructions: {user_prompt}
Requested duration: {target_seconds}
Validation error: {validation_error}
Source constraints: {source_constraints_json}
Selected candidate evidence: {candidates_json}
Invalid proposed plan: {plan_json}
""".strip()
