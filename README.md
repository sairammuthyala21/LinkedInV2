# LinkedIn Job Scraper v2 — Keyword-Based Search

Scrapes LinkedIn **public** job listings (no login required) using keyword-based search.

## Why v2?

LinkedIn no longer respects filter URL parameters (`f_JT`, `f_E`, `f_WT`) on the guest search endpoint. This version embeds all filters directly into the `keywords` query string and post-filters results on our side for accuracy.

## How It Works

1. **Builds a rich keyword string** from all inputs:
   ```
   {jobTitle} {skills} {jobTypeKeyword} {workTypeKeyword} {experienceLevelKeyword}
   ```
   Example: `Backend Developer .NET Contract OR Temporary Hybrid Mid-Senior Level`

2. **Searches LinkedIn** using only `keywords` + `geoId` + `f_TPR` (date posted)

3. **Post-filters** each job's detail page by employment type. For `jobType=C`, it also checks the title and description for W-2, C2C, 1099, independent contractor, and agency restrictions. It saves both clear matches (`keep`) and uncertain listings (`review`), and skips clear W-2-only or agency-blocked jobs.

4. **Keeps paginating** until `maxJobs` matching results are collected

## Inputs

| Field | Type | Description | Example |
|---|---|---|---|
| `jobTitle` | string | Job title to search for | `Backend Developer .NET` |
| `skills` | array | Skills to include | `[".NET", "C#"]` |
| `location` | string | Location (auto-resolved to geoId) | `United States` |
| `datePosted` | select | `anyTime` / `pastDay` / `pastWeek` / `pastMonth` / `custom` | `custom` |
| `customHours` | integer | Hours to look back when `datePosted=custom` (required for Custom) | `2` |
| `jobType` | select | `F`=Full-time, `C`=Contract, etc. | `C` |
| `workType` | select | `1`=On-site, `2`=Remote, `3`=Hybrid | `3` |
| `experienceLevel` | select | `1`=Internship … `6`=Executive | `4` |
| `maxJobs` | integer | Max matching jobs to scrape | `5` |

## Keyword Mapping

| Input Code | Keyword Embedded |
|---|---|
| `jobType=F` | `Full Time` |
| `jobType=C` | `Contract OR Temporary` |
| `workType=2` | `Remote` |
| `workType=3` | `Hybrid` |
| `experienceLevel=4` | `Mid-Senior Level` |

For example, `{"jobTitle":"Software Engineer","datePosted":"custom","customHours":2}` sends `f_TPR=r7200` to LinkedIn. One hour sends `f_TPR=r3600`.

## Output Fields

| Field | Description |
|---|---|
| `title` | Job title |
| `companyName` | Company name |
| `companyUrl` | LinkedIn company page URL |
| `location` | Job location |
| `postedTime` | Human-readable time (e.g. "2 hours ago") |
| `publishedAt` | ISO date (e.g. "2026-08-06") |
| `description` | Full job description (Markdown) |
| `contractType` | Employment type (Full-time, Contract, etc.) |
| `experienceLevel` | Seniority level |
| `workType` | Job function |
| `sector` | Industry sector |
| `salary` | Salary range (if available) |
| `applicationsCount` | Number of applicants |
| `jobUrl` | Direct link to the job posting |

## Test the Contract Filter

Run the local phrase and parser tests:

```bash
python3 -m unittest discover -s tests -v
```

For a live 10-output check, run the LinkedIn actor with:

```json
{"jobTitle":"Software Engineer","location":"United States","datePosted":"pastWeek","jobType":"C","maxJobs":10}
```

The dataset should contain 10 saved jobs when enough listings are accessible. The run log shows `CONTRACT KEEP`, `CONTRACT REVIEW`, and `SKIP` with reasons. Review the saved jobs' titles and descriptions against those log decisions. LinkedIn may rate-limit direct local requests, so the actor's normal request delays and configured proxy are preferable for this live check.

## Deploy to Apify

```bash
cd linkedin-job-scraper-v2
apify push
```
