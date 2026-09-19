# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/jferreiros/vortex/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                 |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------- | -------: | -------: | ------: | --------: |
| vortex/\_\_main\_\_.py               |       11 |       11 |      0% |      3-20 |
| vortex/clinic/\_\_init\_\_.py        |        9 |        1 |     89% |        24 |
| vortex/clinic/client.py              |      252 |       60 |     76% |68, 105-107, 130, 147-149, 158, 163, 349-351, 371-375, 386, 388, 393, 400-406, 409-413, 416-420, 423-427, 437-448, 461-483, 488-491, 494, 520, 576, 580, 735 |
| vortex/clinic/fixtures.py            |       28 |        0 |    100% |           |
| vortex/contract.py                   |      423 |       29 |     93% |872-875, 879, 888, 894-895, 901, 905-911, 915, 919-921, 936, 951, 963, 969, 973, 979, 983, 987, 1007 |
| vortex/conversation/language.py      |       71 |        7 |     90% |137-138, 186-187, 195-199 |
| vortex/conversation/prompt.py        |       37 |        0 |    100% |           |
| vortex/conversation/stt\_context.py  |       41 |        3 |     93% |116, 125-126 |
| vortex/conversation/turns.py         |       34 |        0 |    100% |           |
| vortex/diary/tools.py                |      311 |       31 |     90% |248, 251, 321-322, 331-332, 335, 345-348, 406, 422, 424, 434, 496, 532, 556-557, 666-667, 710-711, 719-720, 725-726, 747, 795-796, 867 |
| vortex/identity/tools.py             |      195 |       40 |     79% |183-189, 201-202, 215, 225-230, 247, 251-256, 258-263, 267-269, 272-277, 288, 294, 300, 373-374, 420, 424-427, 433, 476, 509, 526 |
| vortex/line/pipecat\_voice.py        |      176 |       83 |     53% |71-72, 79-226, 230, 321, 444-447, 473-474, 499-519 |
| vortex/line/server.py                |       70 |       18 |     74% |46-48, 61-62, 67, 72, 80-82, 90-92, 97-102 |
| vortex/line/session.py               |      153 |        3 |     98% |197, 266, 317 |
| vortex/line/stub\_voice.py           |       43 |        7 |     84% | 34, 57-62 |
| vortex/line/submit.py                |       47 |       22 |     53% |41, 48-66, 69, 89 |
| vortex/line/twilio.py                |       77 |        3 |     96% |61, 153, 160 |
| vortex/line/ulaw.py                  |       49 |       12 |     76% |22, 34-40, 53-56 |
| vortex/models.py                     |       83 |        3 |     96% |88-90, 162 |
| vortex/observability/\_\_init\_\_.py |        3 |        0 |    100% |           |
| vortex/observability/agents.py       |       24 |        0 |    100% |           |
| vortex/observability/auth.py         |       33 |        2 |     94% |    28, 30 |
| vortex/observability/calllog.py      |       67 |       10 |     85% |42-44, 112, 119-120, 125-128 |
| vortex/observability/console.py      |      410 |       42 |     90% |36-37, 57, 67, 77, 88, 99, 114, 156-161, 204, 227, 304, 346, 361-363, 417, 456, 485, 493-494, 498-499, 517-521, 548, 569-571, 640, 654, 731-732, 739, 828 |
| vortex/observability/demo.py         |       61 |        0 |    100% |           |
| vortex/observability/explain.py      |      212 |       33 |     84% |150, 172, 181, 183-184, 194, 196, 198, 201, 207, 227-229, 244, 251-263, 335, 377-380, 419 |
| vortex/observability/insights.py     |      109 |        9 |     92% |32, 71, 74-75, 77, 80, 130, 150, 160 |
| vortex/observability/live.py         |      707 |      171 |     76% |60-66, 74, 77-78, 83-88, 96-97, 106, 114, 125-143, 147, 151-153, 159, 170, 176, 181, 188, 196, 216-218, 224, 229, 234, 237, 243-244, 289-290, 352, 356, 371-374, 383-387, 400-403, 430, 449-450, 532-549, 562-565, 607-615, 663-665, 738-762, 766-767, 793-794, 838-839, 842-843, 875-877, 910-923, 936-970, 975, 994-999, 1004, 1014 |
| vortex/observability/shell.py        |      100 |        4 |     96% |122-123, 135-136 |
| vortex/observability/tracing.py      |      156 |       84 |     46% |53-63, 67-79, 85-88, 96, 107, 112-114, 140, 142, 144, 146, 148, 150-151, 157-163, 168-189, 193-198, 202, 210-214, 229-266, 275-288, 299-305, 309-311 |
| vortex/observability/view.py         |      233 |       21 |     91% |68, 70, 72, 74, 86, 88, 91, 112, 131-132, 141, 151, 184-185, 228-229, 272-276 |
| vortex/rules/eligibility.py          |       99 |       15 |     85% |90, 93, 126, 144, 148, 159, 237, 291-304, 310, 313-315 |
| vortex/rules/facts.py                |       84 |        2 |     98% |  200, 202 |
| vortex/rules/geo.py                  |       63 |       10 |     84% |215-217, 220-225, 247 |
| vortex/rules/tools.py                |      127 |       21 |     83% |144-145, 193-200, 296, 300, 332, 353, 374, 383-389, 392, 394, 400 |
| vortex/rules/triage.py               |       57 |        5 |     91% |205-206, 217, 225, 230 |
| vortex/settings.py                   |      175 |        1 |     99% |       265 |
| vortex/tools.py                      |       93 |        7 |     92% |255, 262, 273-275, 277, 296 |
| **TOTAL**                            | **4923** |  **770** | **84%** |           |

6 empty files skipped.


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/jferreiros/vortex/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/jferreiros/vortex/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/jferreiros/vortex/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/jferreiros/vortex/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fjferreiros%2Fvortex%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/jferreiros/vortex/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.