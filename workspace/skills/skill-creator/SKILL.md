---
id: skill-creator
name: skill-creator
description: Guide for creating effective skills
---

# Skill Creator Guide

A skill should be a reusable capability that the agent can load on demand.

## Skill File Structure

workspace/skills/{skill-name}/
└── SKILL.md

## SKILL.md Format

```markdown
---
id: skill-id
name: Skill Name
description: What this skill does
---

# Skill Title

## Overview

Brief description...

## Usage

How to use this skill...

Best Practices

- Keep skills focused on one capability
- Include code examples
- Document prerequisites
```
