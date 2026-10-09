# 0019. A project picks its own skills, and their scripts run as typed tools

Status: accepted

## Context

ADR 0005 gave each role Agent Skills through `pydantic-ai-skills`, with
progressive disclosure already in place: an agent's prompt lists only the
name and description of its role's skills, `load_capability` brings one
skill's instructions in, and `read_skill_resource` reads a file inside that
skill's folder and nowhere else.

Which skills a role has was fixed in `Role.skills`, in this library. The
first real squad needed more: product-discovery and market-research skills
for the Product PM, and a design foundation plus a visual-direction skill
for the Designer, all from third-party repositories. Three things stood in
the way.

- **The mapping was the library's.** A project could add a directory with
  `skills_dirs`, but had no way to say which role uses what in it.
- **Real repositories are not skill libraries.** `pydantic-ai-skills` reads
  a library as a folder whose immediate children are skills, each in a
  folder named after it. `phuryn/pm-skills` nests them
  (`pm-product-discovery/skills/<skill>/`), `ui-ux-pro-max-skill` keeps
  them under a hidden folder, and `taste-skill` has a folder `taste-skill`
  whose `SKILL.md` names the skill `design-taste-frontend`, which the
  loader rejects.
- **A repository's workflows are not skills.** `pm-skills` chains its
  skills in slash commands (`commands/discover.md`): Markdown files that
  sit outside every skill folder, so no skill tool can read them, and that
  nothing here could invoke anyway.
- **`run_skill_script` is too open for third-party code.** It runs any
  script in the skill with arguments the model writes freely. The design
  foundation skill's `search.py` can write a design system to disk, at a
  path given on the command line.

## Decision

- **The library keeps the mechanism; the project brings the content.** A
  `SkillsConfig` (`pydantic_squads.product.skills_config`) holds the
  directories where the project's skills are installed, the patterns
  picking skills for each role, rules added to each role's principles, and
  the skill scripts declared as tools. `ProductSquad(skills=...)` takes
  one; `pydantic-squads chat --config FILE` reads it from the `skills:`
  section of a YAML file. What it picks adds to `Role.skills`, it never
  replaces it.
- **No third-party skill is versioned here from now on.**
  `pydantic-squads skills install <owner/name>` shallow-clones a
  repository into `~/.squads/skills/`. The skills already bundled under
  `product/skills/` (ADR 0005, with their notice file) stay.
- **A registry finds skills wherever they are.**
  `pydantic_squads.product.skill_registry.SkillRegistry` walks the
  configured directories to any depth, reads each `SKILL.md`'s frontmatter
  for `name` and `description`, and selects by glob on the name or on the
  location, with `!` to leave matches out. A `SKILL.md` without usable
  frontmatter is skipped, not fatal.
- **Each role gets a staged library.** The skills picked for a role are
  linked into a temporary folder, one link per skill, named by the
  frontmatter name (a command is a small generated folder there instead). That is the shape `pydantic-ai-skills` reads, so ADR
  0005's loading, scoping and path containment apply unchanged, to the
  role's project skills only.
- **A command reaches a role as a skill.** The registry also lists every
  Markdown file outside a skill whose frontmatter has a `description`.
  One picked under `commands` is written into the role's staged library
  as a skill named after the file, with a short note that it is a workflow
  to follow step by step. It is generated from the installed file each
  time the squad is built. The alternative, copying the sequence of skills
  into the role's rules, would go stale on the first upstream change.
- **A project skill's scripts run only as declared, typed tools.** For a
  project skill, `run_skill_script` sees no script at all. A
  `SkillToolSpec` names one script, the roles that get it, its parameters
  (type, choices, range, flag) and `fixed_args`.
  `pydantic_squads.product.skill_tools.SkillTool` validates the model's
  arguments with a Pydantic model built from the spec, refuses a value
  starting with `-`, and runs the script as an argument list with no shell,
  a timeout and the skill's folder as working directory. `fixed_args`
  belong to the project: a destination such as `--output-dir` is never the
  model's to choose.
- **A tool that writes pauses for the human.** `approval` defaults to
  true and defers the call as `DeferredToolRequests`, the same path as a
  note write to `design-system/**` (ADR 0007). So an approval tool can only
  be declared for a role whose run can pause, the Facilitator or the
  Designer; anything else is refused when the squad is built.
  `approval: false` is for a script that writes nothing, and
  `Role.scripts` still rules: `"never"` forbids declared tools,
  `"free"` lifts the approval.
- **Role rules are config, not role content.** Rules such as "the
  foundation skill wins on tokens, the taste skill on composition" name
  specific skills, so they live next to the mapping that brings those
  skills in. `examples/skills.yaml` carries the Phase 1 set.

The names differ from the first sketch of this feature: the tools are
`load_capability` and `read_skill_resource` (ADR 0005), not `load_skill`
and `read_skill_file`. Writing a second loader to rename them would have
duplicated tested behavior.

## Consequences

- A project wires third-party skills to roles with a YAML file and no
  Python, and the library carries none of their content or licenses.
- A project skill may not share a name with a skill the role already has:
  the loader refuses duplicates. Leave one out with a `!` pattern. The same
  holds for a command named like one of the role's skills.
- A script-backed skill needs one declaration per use, with its
  parameters. That is the point: what the model can make the script do is
  written down and reviewable.
- A persisted design system is written by the script, not by `write_note`.
  It lands in the knowledge base only because the project points
  `--output-dir` at it, and it is guarded by the tool's approval instead of
  by `Permissions`.
- Only Python scripts are supported, run on the squad's own interpreter.
- The staged libraries are symbolic links in a temporary folder, removed
  when the process ends. Platforms without symbolic links are not
  supported.
- Later phases only need config: the Marketing PM, Growth PM and Product
  Owner mappings, trend listening and a dev hand-off format are listed in
  the roadmap, not built.
