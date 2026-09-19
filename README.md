# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/jferreiros/vortex/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                   |    Stmts |     Miss |   Cover |   Missing |
|--------------------------------------- | -------: | -------: | ------: | --------: |
| vortex/\_\_main\_\_.py                 |       11 |       11 |      0% |      3-20 |
| vortex/clinic/\_\_init\_\_.py          |        9 |        1 |     89% |        24 |
| vortex/clinic/client.py                |      252 |       60 |     76% |68, 105-107, 130, 147-149, 158, 163, 349-351, 371-375, 386, 388, 393, 400-406, 409-413, 416-420, 423-427, 437-448, 461-483, 488-491, 494, 520, 576, 580, 735 |
| vortex/clinic/fixtures.py              |       28 |        0 |    100% |           |
| vortex/contract.py                     |      425 |       29 |     93% |877-880, 884, 893, 899-900, 906, 910-916, 920, 924-926, 941, 956, 968, 974, 978, 984, 988, 992, 1012 |
| vortex/conversation/language.py        |       71 |        7 |     90% |137-138, 186-187, 195-199 |
| vortex/conversation/prompt.py          |       43 |        0 |    100% |           |
| vortex/conversation/stt\_context.py    |       56 |        2 |     96% |   305-306 |
| vortex/conversation/turns.py           |       95 |        0 |    100% |           |
| vortex/diary/tools.py                  |      311 |       30 |     90% |248, 251, 321-322, 331-332, 335, 345-348, 406, 422, 424, 434, 496, 532, 556-557, 666-667, 710-711, 719-720, 726, 747, 795-796, 867 |
| vortex/identity/dictation.py           |       79 |        5 |     94% |230-231, 234, 245, 249 |
| vortex/identity/tools.py               |      218 |       35 |     84% |159, 260, 270-275, 292, 296-301, 303-317, 321-323, 326-331, 342, 348, 359, 437-438, 484, 488-491, 497, 546, 579, 596 |
| vortex/line/aic\_filter.py             |       22 |        1 |     95% |        45 |
| vortex/line/gemini\_live\_voice.py     |       91 |       55 |     40% |102-106, 124-225, 230-250 |
| vortex/line/llm\_timeout.py            |      124 |        2 |     98% |  259, 272 |
| vortex/line/pipecat\_voice.py          |      234 |       93 |     60% |107-108, 115-299, 303, 405, 556, 606-609, 635-636, 704-724 |
| vortex/line/privacy.py                 |       72 |        5 |     93% |61, 85, 88, 94, 154 |
| vortex/line/server.py                  |       73 |       20 |     73% |46-48, 61-62, 67, 72, 80-82, 90-92, 94-96, 101-106 |
| vortex/line/session.py                 |      153 |        3 |     98% |197, 266, 317 |
| vortex/line/smart\_turn\_ab.py         |      152 |        7 |     95% |115, 126, 198-200, 208, 212 |
| vortex/line/stub\_voice.py             |       43 |        7 |     84% | 34, 57-62 |
| vortex/line/submit.py                  |       47 |       22 |     53% |41, 48-66, 69, 89 |
| vortex/line/twilio.py                  |       77 |        3 |     96% |61, 153, 160 |
| vortex/line/ulaw.py                    |       49 |       12 |     76% |22, 34-40, 53-56 |
| vortex/models.py                       |       83 |        3 |     96% |88-90, 162 |
| vortex/observability/\_\_init\_\_.py   |        3 |        0 |    100% |           |
| vortex/observability/agents.py         |       24 |        0 |    100% |           |
| vortex/observability/auth.py           |       33 |        2 |     94% |    28, 30 |
| vortex/observability/calllog.py        |       67 |       10 |     85% |42-44, 112, 119-120, 125-128 |
| vortex/observability/console.py        |      411 |       43 |     90% |36-37, 57, 67, 77, 88, 99, 115-116, 158-163, 206, 229, 306, 346, 361-363, 417, 456, 485, 493-494, 498-499, 517-521, 548, 569-571, 640, 654, 731-732, 739, 828 |
| vortex/observability/demo.py           |       61 |        0 |    100% |           |
| vortex/observability/explain.py        |      309 |       63 |     80% |172, 181, 183-184, 194, 196, 198, 201, 207, 227-229, 245, 252-264, 336, 378-381, 432-438, 457, 460-462, 469, 492-511, 517, 560, 562-569, 581, 624 |
| vortex/observability/icons.py          |       12 |        0 |    100% |           |
| vortex/observability/insights.py       |      109 |        9 |     92% |32, 75, 78-79, 84, 95, 135, 155, 165 |
| vortex/observability/live.py           |      786 |      168 |     79% |67-73, 81, 84-85, 90-95, 103-104, 116, 127-145, 149, 172, 183, 190, 198, 218-220, 226, 231, 236, 239, 245-246, 291-292, 354, 358, 373-376, 385-389, 402-405, 432, 451-452, 533, 539, 564, 568-570, 574-577, 593, 602-619, 632-635, 677-685, 731-733, 803-808, 820-833, 854-855, 861, 871-872, 943-944, 947-948, 981-983, 1016-1029, 1042-1076, 1081, 1100-1105, 1110, 1120 |
| vortex/observability/shell.py          |      110 |        4 |     96% |133-134, 146-147 |
| vortex/observability/tracing.py        |      156 |       84 |     46% |53-63, 67-79, 85-88, 96, 107, 112-114, 140, 142, 144, 146, 148, 150-151, 157-163, 168-189, 193-198, 202, 210-214, 229-266, 275-288, 299-305, 309-311 |
| vortex/observability/view.py           |      243 |       20 |     92% |69, 71, 75, 87, 89, 92, 121, 140-141, 150, 160, 193-194, 240-241, 284-288 |
| vortex/observability/wall\_timeline.py |       79 |       68 |     14% |20-94, 106-114, 118, 127-138, 142, 150-153, 164-177 |
| vortex/rules/eligibility.py            |       99 |       15 |     85% |90, 93, 126, 144, 148, 159, 237, 291-304, 310, 313-315 |
| vortex/rules/facts.py                  |       84 |        2 |     98% |  200, 202 |
| vortex/rules/geo.py                    |      103 |       11 |     89% |239, 242-243, 255-257, 272, 278, 288-289, 330 |
| vortex/rules/tools.py                  |      132 |       21 |     84% |145-146, 194-201, 311, 315, 347, 368, 389, 398-404, 407, 409, 415 |
| vortex/rules/triage.py                 |       57 |        5 |     91% |205-206, 217, 225, 230 |
| vortex/settings.py                     |      212 |        2 |     99% |  354, 506 |
| vortex/tools.py                        |       93 |        7 |     92% |257, 264, 275-277, 279, 298 |
| **TOTAL**                              | **6001** |  **947** | **84%** |           |

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