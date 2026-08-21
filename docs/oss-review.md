# Open-source reuse review

Verified on 2026-08-21. Recheck upstream license, notice files, and the pinned source manifest before changing reuse mode.

| Project | Verified commit | License | Reuse mode | Intended learning or reuse | Main risk |
|---|---|---|---|---|---|
| [AgentMesh-JobAgent](https://github.com/jiyangnan/AgentMesh-JobAgent) | `291d9dcee29455990ec51935ee15cd911440a297` | Apache-2.0 | Adapter or subprocess | Platform isolation, connector workflow, preview/delivery/audit separation, resumability | Cloud contracts and browser adapters may change; preserve license and notices |
| [open-boss](https://github.com/yinren112/open-boss) | `f1e92275340007ebb460417e5e0d1be14ce1566a` | MIT | Adapter or reference | Real-JD requirement, dry-run, explicit approval, privacy, browser-profile isolation, stop conditions | Platform DOM is unstable; retain the MIT notice when copying compatible material |
| [Auto-JobHunter](https://github.com/jolie-z/Auto-JobHunter) | `4f9dec38978035a87d34cab5b15914dc8688e6f0` | Personal, educational, non-commercial | Reference only | High-level SQLite to rules to LLM evaluation to RPA observation | License is incompatible with unrestricted reuse; do not copy source, prompts, or implementation structure |

## Gate

Before introducing external material, record whether it is copied, used as a dependency, wrapped through subprocess, integrated through an adapter, or studied as reference only. Record attribution, notice obligations, commercial restrictions, and copyleft effects.

Domain code must remain independent of every upstream project. An upstream adapter can be removed without changing candidate, job intelligence, optimizer, approval, or audit contracts.

The machine-readable registry is [the Skill Context source manifest](../skills/job-hunting/references/oss/source-manifest.yaml).
