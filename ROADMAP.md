# USD Studio Roadmap

## Vision

Build a browser-based USD production workspace for loading composed scenes, inspecting and editing them, running physics, authoring camera and lighting changes, and generating still images and video.

## Current Milestone: Interactive Viewer and Physics MVP

### Completed

- Load server-local USD scenes by path or native Windows file picker.
- Preserve relative references, payloads, textures, and sublayers when loading local scenes.
- Upload complete scene folders and ZIP packages while preserving directory structure.
- Secure package extraction with traversal, symbolic-link, file-count, and size protections.
- Discover a likely root scene and allow selection among multiple USD scenes in a package.
- Render scenes with `ovrtx` and inject a camera, lights, and render product when needed.
- Stream the viewport to the browser through `ovstream` WebRTC.
- Reconnect WebRTC cleanly when replacing the active scene.
- Orbit, pan, and zoom the camera with viewport mouse controls.
- Pick and select scene prims.
- Render still images.
- Run `ovphysx` in an isolated CPU worker process.
- Discover rigid bodies and provide initialize, play, pause, step, and reset controls.
- Apply simulated rigid-body poses to the rendered scene while preserving authored geometry scale.
- Validate the basic workflow with falling-box and referenced nut-and-bolt scenes.

### Known Limitations

- Physics support is currently focused on rigid-body poses and has only been validated against a small set of scenes.
- Articulations, deformables, particles, sensors, and less common joint configurations are not yet validated.
- Selected objects cannot yet be translated, rotated, or scaled from the UI.
- A rigid body cannot yet be interactively lifted and released into a running simulation.
- Runtime edits are not authored into a persistent USD override layer.
- Scene hierarchy and detailed prim properties are not exposed in the UI.
- Lighting and camera properties cannot yet be authored from the UI.
- There is no unified timeline, keyframe system, deterministic recording flow, or MP4 export workflow.
- The native USD picker is a local-workstation feature; remote deployments require uploads or another asset service.
- Complex scenes still need broader testing for composition, materials, textures, memory use, and performance.

## Phase 1: Scene Inspection and Object Manipulation

### Goal

Allow a user to select an object, reposition it, and release it into physics.

### Planned Work

- Add a searchable scene hierarchy with selected-prim synchronization.
- Display selected-prim type and transform properties.
- Add numeric translate, rotate, and scale controls.
- Add backend APIs for safe transform reads and writes.
- Define how transform edits interact with active physics.
- Support a pause, reposition, synchronize, and resume workflow for rigid bodies.
- Add viewport transform gizmos after numeric editing is reliable.
- Add undo and redo for authored edits.
- Store non-destructive edits in a USD override layer.

### Acceptance Target

Load the nut-and-bolt scene, select either rigid body, lift and reposition it, then release it and observe the updated simulation through the live viewport.

## Phase 2: Lighting and Camera Authoring

- List and select existing cameras and lights.
- Create cameras and common light types.
- Edit light intensity, exposure, color, temperature, and orientation.
- Edit camera transform, focal length, clipping, and depth of field.
- Save and restore named camera poses and shot presets.
- Add simple environment and background controls.

## Phase 3: Timeline and Animation

- Introduce a shared playback timeline and frame rate.
- Synchronize physics, authored animation, and rendering by frame.
- Add camera and object transform keyframes.
- Add playback ranges, scrubbing, and looping.
- Support orbit and fly-through camera paths.
- Make offline stepping deterministic enough for media export.

## Phase 4: Media Production

- Render configurable image sequences.
- Encode MP4 video from deterministic rendered frames.
- Expose resolution, frame rate, duration, format, and quality settings.
- Add render progress, cancellation, and output management.
- Support transparent backgrounds and common image formats where available.
- Add reusable render and shot presets.

## Phase 5: Complex Scene Hardening

- Report unresolved references, payloads, textures, and other composition errors clearly.
- Validate larger scenes with nested references and varied materials.
- Test additional rigid-body joints and articulation workflows.
- Add loading progress and cancellation for large scenes.
- Profile GPU memory, CPU memory, upload size, and frame performance.
- Improve recovery when rendering, streaming, or physics initialization fails.
- Add automated integration scenes and regression tests for core workflows.

## Engineering Backlog

- Add an ESLint 9 flat configuration so frontend linting runs again.
- Expand backend endpoint and physics-controller tests.
- Add frontend interaction tests for scene loading and stream reconnection.
- Make runtime directories independent of the process working directory.
- Clarify local-only and remotely deployable scene-loading modes.
- Review authentication, CORS, and filesystem access before any remote deployment.
- Document supported USD and PhysX feature boundaries as testing expands.

## Next Task

Begin Phase 1 with selected-prim inspection and numeric transform editing:

1. Add an API to return the selected prim's current local transform.
2. Add an API to update translation and rotation while physics is paused.
3. Add a compact transform editor to the frontend.
4. Validate edits on static prims and on the nut-and-bolt rigid bodies.
5. Define and test the synchronization step required before resuming physics.

## New Thread Handoff

Use the following request to continue in a new coding thread:

> Read `README.md` and `ROADMAP.md`. Begin Phase 1 with selected-prim inspection and numeric transform editing. First inspect the existing selection, renderer transform, and physics synchronization code, then propose the smallest end-to-end implementation that lets me reposition a nut or bolt before resuming physics.
