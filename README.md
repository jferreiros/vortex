# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/jferreiros/vortex/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                 |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------- | -------: | -------: | ------: | --------: |
| vortex/\_\_main\_\_.py               |       11 |       11 |      0% |      3-20 |
| vortex/clinic/\_\_init\_\_.py        |        9 |        1 |     89% |        24 |
| vortex/clinic/client.py              |      234 |       61 |     74% |68, 105-107, 130, 147-149, 158, 163, 349-351, 371-375, 386, 388, 393, 400-406, 409-413, 416-420, 423-427, 437-448, 461-483, 488-491, 494, 520, 576, 580, 660, 680 |
| vortex/clinic/fixtures.py            |       26 |        0 |    100% |           |
| vortex/contract.py                   |      396 |       28 |     93% |811-814, 818, 827, 833-834, 840, 844-850, 854, 858-860, 875, 890, 902, 908, 912, 918, 922, 926 |
| vortex/conversation/language.py      |       71 |        7 |     90% |137-138, 186-187, 195-199 |
| vortex/conversation/prompt.py        |       37 |        0 |    100% |           |
| vortex/conversation/stt\_context.py  |       41 |        3 |     93% |116, 125-126 |
| vortex/conversation/turns.py         |       34 |        0 |    100% |           |
| vortex/diary/tools.py                |      311 |       31 |     90% |248, 251, 321-322, 331-332, 335, 345-348, 406, 422, 424, 434, 496, 532, 556-557, 666-667, 710-711, 719-720, 725-726, 747, 795-796, 867 |
| vortex/identity/tools.py             |      195 |       40 |     79% |183-189, 201-202, 215, 225-230, 247, 251-256, 258-263, 267-269, 272-277, 288, 294, 300, 373-374, 420, 424-427, 433, 476, 509, 526 |
| vortex/line/pipecat\_voice.py        |      175 |       83 |     53% |70-71, 78-224, 228, 319, 442-445, 471-472, 497-517 |
| vortex/line/server.py                |       68 |       18 |     74% |45-47, 60-61, 66, 71, 79-81, 88-90, 95-100 |
| vortex/line/session.py               |      145 |        2 |     99% |  195, 264 |
| vortex/line/stub\_voice.py           |       43 |        7 |     84% | 34, 57-62 |
| vortex/line/submit.py                |       47 |       22 |     53% |41, 48-66, 69, 89 |
| vortex/line/twilio.py                |       77 |        3 |     96% |61, 153, 160 |
| vortex/line/ulaw.py                  |       49 |       12 |     76% |22, 34-40, 53-56 |
| vortex/models.py                     |       83 |        3 |     96% |88-90, 162 |
| vortex/observability/\_\_init\_\_.py |        3 |        0 |    100% |           |
| vortex/observability/auth.py         |       33 |        2 |     94% |    28, 30 |
| vortex/observability/calllog.py      |       67 |       10 |     85% |42-44, 112, 119-120, 125-128 |
| vortex/observability/demo.py         |       61 |        0 |    100% |           |
| vortex/observability/explain.py      |      204 |       34 |     83% |150, 159, 162, 168, 170-171, 179, 181, 183, 186, 192, 212-214, 229, 236-248, 320, 362-365, 404 |
| vortex/observability/live.py         |      699 |      191 |     73% |58-64, 72, 75-76, 81-86, 94-95, 104, 112, 123-141, 145, 149-151, 157, 168, 176-180, 186, 194, 218, 223, 228, 231, 237-238, 283, 346, 350, 365-368, 377-381, 394-397, 424, 443-444, 523-540, 552-555, 597-605, 653-655, 725-749, 753-754, 780-781, 816-817, 820-821, 853-855, 881-884, 888-900, 908-953, 964-981, 991 |
| vortex/observability/view.py         |      233 |       21 |     91% |68, 70, 72, 74, 86, 88, 91, 112, 131-132, 141, 151, 184-185, 228-229, 272-276 |
| vortex/rules/eligibility.py          |      103 |       17 |     83% |84, 87, 120, 138, 142, 153, 231, 250, 261, 302-315, 321, 324-326 |
| vortex/rules/facts.py                |       59 |        2 |     97% |  118, 120 |
| vortex/rules/geo.py                  |       63 |       10 |     84% |215-217, 220-225, 247 |
| vortex/rules/tools.py                |      129 |       31 |     76% |131-132, 148-153, 168, 171-172, 179-185, 238, 264, 283, 287, 319, 340, 361, 370-376, 379, 381, 387 |
| vortex/rules/triage.py               |       57 |        5 |     91% |205-206, 217, 225, 230 |
| vortex/settings.py                   |      171 |        1 |     99% |       257 |
| vortex/tools.py                      |       86 |        6 |     93% |243, 254-256, 258, 277 |
| **TOTAL**                            | **4020** |  **662** | **84%** |           |

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