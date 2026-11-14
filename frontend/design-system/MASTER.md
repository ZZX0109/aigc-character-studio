# Character Studio editor design

A local professional character-editing workspace. Its visual hierarchy follows the task: character → 3D viewport → local adjustment → saved references. Warm off-white surfaces, charcoal text, and restrained burnt orange for editing and export. It should feel like a small desktop creative tool, with no marketing hero or invented AI-generation features.

The ui-ux-pro-max design-system search returned a marketing-page pattern twice; that pattern was not adopted. The verified professional-tool Minimalism/Swiss style guidance, readable contrast, keyboard access and explicit interaction feedback inform this hand-designed workspace. The Three.js stack search matched OrbitControls imports and container-based renderer sizing.

Use system sans fonts (including PingFang SC) for fully local operation, no remote font requests. Body text 14–16px and metadata 12px minimum. Native range and number controls have persistent labels. Every icon action has a text or accessible label. Screen-reader status is polite; errors use alert. Visible keyboard focus and reduced-motion behavior are required. All export thumbnails are actual renders from the current geometry, never decorative face images.

Desktop: narrow character list, flexible viewport, 300px controls. At tablet widths move control panel below viewport; at small widths collapse to one readable column. Orbit dragging has front/45°/profile button alternatives. No automatic camera motion.


Model import extends the existing workspace rather than replacing the editor. A native dialog keeps file discovery, local import feedback, and official-source guidance together. The targeted UX search matched submission feedback, inline validation, and contextual live status; these inform progress/error states. No account or license acceptance is automated in the interface.

Paired export is the primary research export; the single-version export remains available. Before/after renders share baseline framing, camera, dimensions and lighting. An uncalibrated parametric model is explicitly marked and its nasal control is disabled while neutral viewing remains available.
