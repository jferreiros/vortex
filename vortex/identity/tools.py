"""identity/ tools - who is calling.

Owner: the identity lane. Replace each ``stub_*`` call with the real logic.
Keep the signatures exactly as ``vortex/contract.py`` declares them.

What the docs say this lane must get right (clinic docs, "Six things worth knowing"):

- /directory filters on exact fields. A field that does not match excludes the
  patient. Use name + date_of_birth to split two people with the same name.
- Confirm on a second field before you trust a match.
- Submit the record's name and ids, never what the caller said.
- ``from_number`` is a hint, never identification. The caller is not always
  the patient (a parent for a child, a daughter for her father).
- A caller the directory does not know cannot be booked. Register first.
- DNI: 8 digits + letter. NIE: X/Y/Z + 7 digits + letter. The letter is
  ``"TRWAGMYFPDXBNJZSQVHLCKE"[number % 23]`` where a NIE's leading X/Y/Z
  counts as 0/1/2. A wrong letter is a 422 at submit time.
"""

from __future__ import annotations

from vortex import contract
from vortex.contract import (
    BuildRegistrationInput,
    FindPatientInput,
    FindPatientResult,
    NationalIdCheck,
    RegistrationResult,
    ToolContext,
    ValidateNationalIdInput,
)


async def find_patient(ctx: ToolContext, args: FindPatientInput) -> FindPatientResult:
    """Look the caller up in /directory and decide: found, ambiguous or not_found.

    TODO(identity): query ``ctx.clinic.directory(...)`` with the fields given,
    narrow with ``ctx.from_number`` when the caller gave nothing else, and set
    ``ask_for`` to the field that would split the candidates.
    """
    return await contract.stub_find_patient(ctx, args)


async def validate_national_id(ctx: ToolContext, args: ValidateNationalIdInput) -> NationalIdCheck:
    """Normalise a spoken DNI/NIE and check its letter.

    TODO(identity): implement the mod-23 check. Return ``valid=False`` with the
    expected letter so the conversation can ask the caller to repeat it.
    """
    return await contract.stub_validate_national_id(ctx, args)


async def build_registration(ctx: ToolContext, args: BuildRegistrationInput) -> RegistrationResult:
    """Turn dictated demographics into a ``RegisterAction``.

    TODO(identity): validate the national id (reject with a typed rejection
    when its letter is wrong), normalise the phone to E.164, lower-case the
    email, and check the insurer is one of the catalogue's plan ids.
    """
    return await contract.stub_build_registration(ctx, args)
