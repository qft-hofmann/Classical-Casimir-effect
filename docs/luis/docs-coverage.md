# LUIS documentation reading record

Reviewed 2026-10-27 for [the script checklist](script-checks.md). Sources were
retrieved through the web reader; no cluster account or authenticated service was
accessed. The handbook export identifies itself as printed **2026-10-12**. It is a
snapshot, so newer live storage guidance was checked separately.

## Complete handbook

Read the full text of the official **137-page**
[Cluster_Doc export](https://docs.cluster.uni-hannover.de/doku.php/start?book_ns=guide%3Ato_pdf&book_title=Cluster_Doc&do=export_pdfns),
including application-specific chapters. Printed page numbers below are one-based.
Diagrams/screenshots do not add executable policy; this audit concerns the text and
commands. This is not a visual-layout review of the handbook.

| Pages | Chapter | Checklist destination |
|---|---|---|
| 1 | Cover | Source metadata |
| 2–5 | Quick start, access, intended use, FCH | HOST, ACCOUNT, JOB |
| 6–15 | Connecting, SSH/X2Go, OOD | HOST, NET, C14 |
| 16–24 | Storage, quota, Lustre striping | FS, IO |
| 25–26 | Large datasets | IO |
| 27–32 | Transfers, Unix script endings | IO, NET |
| 33–38 | Rclone/cloud storage | IO09 |
| 39–41 | Archive | IO08 |
| 42–66 | Slurm, parallelism, scheduling, limits, examples, accounting | JOB, C01–C02 |
| 67–77 | Modules, native builds, EasyBuild | ENV |
| 78–81 | Abaqus | C05 |
| 82–85 | ANSYS/CFX | C06 |
| 86–89 | Code-Server | C14 |
| 90–93 | COMSOL | C07 |
| 94–95 | CPMD | C09 |
| 96 | FEKO | C10 |
| 97–98 | Gaussian | C08 |
| 99–105 | Jupyter | C14 |
| 106–107 | LIGGGHTS | C12 |
| 108–113 | MATLAB | C11 |
| 114–119 | Miniforge/Conda | ENV |
| 120–121 | mpiFileUtils | IO |
| 122 | NFFT | C13 |
| 123–126 | uv | ENV12 |
| 127–133 | Remote visualization | C15 |
| 134 | End of work | OPS06 |
| 135–137 | Support | OPS02 |

Also read all **41 slides** of the linked
[2026 introductory course](https://docs.cluster.uni-hannover.de/lib/exe/fetch.php/course/20260122_luis_cluster_intro.pdf).
The slides retain some older examples/limits; conflicts are listed in the checklist.

## Live chapters and supplements

The [public documentation homepage](https://docs.cluster.uni-hannover.de/doku.php/start)
is the entry-point inventory. Its EasyBuild and web-portal links resolve to sections
of the modules and connecting chapters, respectively. Public application chapters
are covered in full by the handbook; live core pages and supplementary services
below were checked in addition. The software catalogue supplies availability
information, not authorization to ignore application-specific licenses.

| Source | What was checked |
|---|---|
| [Quick start/accounts](https://docs.cluster.uni-hannover.de/doku.php/guide/about_the_cluster_system) | Purpose, eligibility, personal accounts, login restrictions |
| [Connecting/OOD](https://docs.cluster.uni-hannover.de/doku.php/guide/connecting_to_cluster) | Host roles, VPN, SSH identities, desktop/portal restrictions |
| [Storage](https://docs.cluster.uni-hannover.de/doku.php/guide/storage_systems) | Full chapter; last-modified 2026-10-15, newer than PDF |
| [Large datasets](https://docs.cluster.uni-hannover.de/doku.php/guide/handling_large_datasets) | Packing, scratch staging, metadata load |
| [Transfers](https://docs.cluster.uni-hannover.de/doku.php/guide/transferring_data) | Dedicated host, tools, line endings |
| [Rclone](https://docs.cluster.uni-hannover.de/doku.php/guide/cloud_storage_rclone) | Providers, credentials, copy/sync semantics |
| [Archive](https://docs.cluster.uni-hannover.de/doku.php/guide/transferring_files_into_the_archive) | Registration, packing, retention workflow |
| [Slurm](https://docs.cluster.uni-hannover.de/doku.php/guide/slurm_usage_guide) | Arrays, user limits, MPP/toolchain rules, accounting |
| [Modules/EasyBuild](https://docs.cluster.uni-hannover.de/doku.php/guide/modules_and_application_software) | Hierarchy, CPU builds, override defaults, application links |
| [Conda](https://docs.cluster.uni-hannover.de/doku.php/guide/soft/miniforge3) | Full chapter; channels, prefixes, caches, module isolation |
| [Apptainer](https://docs.cluster.uni-hannover.de/doku.php/guide/apptainer) | Full chapter; permitted image locations, fakeroot, binds, overlays, concurrency |
| [Hardware](https://docs.cluster.uni-hannover.de/doku.php/resources/computing_hardware) | Full page; live clusterinfo is authoritative, no general compute internet |
| [Software catalogue](https://docs.cluster.uni-hannover.de/doku.php/resources/available_software) | Catalogue structure and application-guide links; package descriptions are not additional script policy |
| [JupyterHub](https://docs.cluster.uni-hannover.de/doku.php/resources/jhub) | Full page, including registration/role/configuration/expiry/FAQ rules |
| [LUHKI](https://docs.cluster.uni-hannover.de/doku.php/resources/luhki_hpc) | Full service/terms/privacy text; AI answers are not binding guidance |
| [System status](https://docs.cluster.uni-hannover.de/doku.php/status/system_status) | Full page; cached status timestamp is not a live health certificate |
| [FAQ](https://docs.cluster.uni-hannover.de/doku.php/guide/cluster_faq) | Full page, including quotas, egress, reservations, mail, memory/CPU failures |
| [Support](https://docs.cluster.uni-hannover.de/doku.php/guide/how_to_get_support) | Full handbook chapter, support details and reproducer requirements |
| [Introductory course](https://docs.cluster.uni-hannover.de/doku.php/course/cluster_introductory_course_online) | Full landing page and all linked slides |
| [Citation](https://docs.cluster.uni-hannover.de/doku.php/guide/citation) | Full page; funding references depend on used equipment |
| [IT usage rules](https://www.luis.uni-hannover.de/it-compliance-und-zugaenge/it-compliance-luh/nutzungsregelungen) | Public principles and account eligibility |
| [Scientific Computing service](https://www.luis.uni-hannover.de/services/computing/scientific-computing) | Access/usage conditions and conflicting published limits |

For precise command semantics, additionally checked primary
[Slurm accounting](https://slurm.schedmd.com/sacct.html) and
[array documentation](https://slurm.schedmd.com/job_array.html): array-element
accounting uses `JobID`, not `JobIDRaw`; queue counting uses `--array` expansion.
The installed local Conda source was inspected for environment registration and
cache selection during the earlier installer review. The current workflow reuses
the existing HOME environment read-only and does not create environments or
download packages. This user-selected location exception is recorded in the
checklist. Its dependency metadata and the operator's 2026-10-29 run have been
inspected: smoke passed and the original 80-point distance curve is complete after
the guard repair, including collection/plotting. The next 150-point curve through
g/a=20 has 142 computed samples and eight MemoryError failures on one node;
see [run status and retry instructions](README.md).

## Scope boundaries and review status

This covers the entire exported user handbook and the public homepage's
policy-bearing supplements. It does not recursively audit the whole internet:
vendor manuals, external provider policies, linked full legal statutes, BIAS,
private project agreements, authenticated portal configuration, old revisions,
wiki administration/source pages and linked example downloads are not independent
certified sources here. Their applicable obligations remain operator checks; the
current BEM bundle does not use the commercial applications or teaching services.

Checklists distinguish a documented rule from a stricter project decision. The
policy is intentionally incomplete as an automated compliance certificate: actual
quotas, headroom estimates, cluster versions, licenses, funding, backup completion,
scaling and account permissions cannot be confirmed offline. The generated review
starts unapproved, and production remains blocked until the required live evidence
and operator review exist. No source is silently treated as proof that those
external checks passed.
