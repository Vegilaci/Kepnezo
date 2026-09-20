#!/usr/bin/env python3
from getpass import getpass

from argon2 import PasswordHasher


password = getpass("Új jelszó: ")
confirm = getpass("Jelszó újra: ")
if not password or password != confirm:
    raise SystemExit("A jelszavak nem egyeznek vagy üresek.")
print(PasswordHasher().hash(password))

