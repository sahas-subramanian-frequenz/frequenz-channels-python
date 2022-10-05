"""Tests for the Merge implementation.

Copyright
Copyright © 2022 Frequenz Energy-as-a-Service GmbH

License
MIT
"""

import asyncio
from typing import List

from frequenz.channels import Anycast, Merge, Sender


async def test_merge() -> None:
    """Ensure Merge receives messages in order."""
    chan1 = Anycast[int]()
    chan2 = Anycast[int]()

    async def send(ch1: Sender[int], ch2: Sender[int]) -> None:
        for ctr in range(5):
            await ch1.send(ctr + 1)
            await ch2.send(ctr + 101)
        await chan1.close()
        await ch2.send(1000)
        await chan2.close()

    senders = asyncio.create_task(send(chan1.get_sender(), chan2.get_sender()))

    merge = Merge(chan1.get_receiver(), chan2.get_receiver())
    results: List[int] = []
    while item := await merge.receive():
        results.append(item)
    await senders
    for ctr in range(5):
        idx = ctr * 2
        # It is hard to get messages from multiple channels in the same order,
        # so we use a `set` to check the next N messages are the same, in any
        # order, where N is the number of channels.  This only works in this
        # example because the `send` method sends values in immeidate
        # succession.
        assert set((results[idx : idx + 2])) == {ctr + 1, ctr + 101}
    assert results[-1] == 1000