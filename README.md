# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/jferreiros/vortex/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                 |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------- | -------: | -------: | ------: | --------: |
| vortex/\_\_main\_\_.py               |       11 |       11 |      0% |      3-20 |
| vortex/clinic/\_\_init\_\_.py        |        9 |        1 |     89% |        24 |
| vortex/clinic/client.py              |      182 |       77 |     58% |42, 52-54, 65, 69, 81-93, 103-193, 243-245, 252-258, 261-265, 268-272, 275-279, 289-297, 310-330, 333-335, 338, 356, 375, 395, 421, 436-437, 441, 461 |
| vortex/clinic/fixtures.py            |       12 |        0 |    100% |           |
| vortex/contract.py                   |      346 |       18 |     95% |663, 672, 678-679, 685, 689-695, 699, 704, 720, 753, 767, 771 |
| vortex/conversation/language.py      |        4 |        4 |      0% |     15-26 |
| vortex/conversation/prompt.py        |       11 |        0 |    100% |           |
| vortex/conversation/turns.py         |       15 |        0 |    100% |           |
| vortex/diary/tools.py                |       94 |       42 |     55% |69-70, 74-78, 99, 101, 103, 105, 107, 109-113, 115-116, 118, 120-121, 123-124, 135-146, 171-173, 176-178, 199, 206 |
| vortex/identity/tools.py             |       64 |       26 |     59% |50, 59-65, 91-96, 105, 111, 113-119, 131, 139-143, 156-158 |
| vortex/line/pipecat\_voice.py        |       84 |       84 |      0% |    26-210 |
| vortex/line/server.py                |       59 |       16 |     73% |42-44, 57-58, 66-68, 75-77, 82-87 |
| vortex/line/session.py               |       62 |        6 |     90% |60, 94, 109-110, 125-126 |
| vortex/line/stub\_voice.py           |       43 |        7 |     84% | 34, 57-62 |
| vortex/line/submit.py                |       47 |       22 |     53% |41, 48-66, 69, 89 |
| vortex/line/twilio.py                |       77 |        3 |     96% |61, 153, 160 |
| vortex/line/ulaw.py                  |       49 |       12 |     76% |22, 34-40, 53-56 |
| vortex/observability/\_\_init\_\_.py |        3 |        0 |    100% |           |
| vortex/observability/auth.py         |       33 |        6 |     82% |     26-31 |
| vortex/observability/calllog.py      |       65 |       19 |     71% |41-43, 87, 106-116, 120-123 |
| vortex/observability/demo.py         |       61 |       61 |      0% |     1-187 |
| vortex/observability/live.py         |      285 |      285 |      0% |     1-412 |
| vortex/observability/view.py         |      228 |       28 |     88% |65, 67, 69, 71, 83, 85, 88, 109, 118, 128-129, 138, 148, 165, 179-180, 194-196, 198, 223-224, 248, 267-271 |
| vortex/rules/tools.py                |       50 |       14 |     72% |80-96, 131, 140-146, 149, 151, 157 |
| vortex/settings.py                   |       50 |        4 |     92% |69, 72, 77, 80 |
| vortex/tools.py                      |       51 |        9 |     82% |182, 185-187, 193-195, 197, 210 |
| **TOTAL**                            | **1995** |  **755** | **62%** |           |

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