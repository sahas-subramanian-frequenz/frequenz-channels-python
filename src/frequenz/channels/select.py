"""Select the first among multiple AsyncIterators.

Expects AsyncIterator class to raise `StopAsyncIteration`
exception once no more messages are expected or the channel
is closed in case of `Receiver` class.

Copyright
Copyright © 2022 Frequenz Energy-as-a-Service GmbH

License
MIT
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, Set, TypeVar

logger = logging.Logger(__name__)
T = TypeVar("T")


@dataclass
class _Selected:
    """A wrapper class for holding values in `Select`.

    Using this wrapper class allows `Select` to inform user code when a
    receiver gets closed.
    """

    inner: Optional[Any]


class Select:
    """Select the next available message from a group of AsyncIterators.

    For example, if there are two async iterators that you want to
    simultaneously wait on, this can be done with:

    ```
    select = Select(name1 = receiver1, name2 = receiver2)
    while await select.ready():
        if msg := select.name1:
            if val := msg.inner:
                # do something with `val`
                pass
            else:
                # handle closure of receiver.
                pass
        elif msg := select.name2:
            # do something with `msg.inner`
            pass
    ```

    If `Select` was created with more `AsyncIterator` than what are read in
    the if-chain after each call to `ready()`, messages coming in the
    additional async iterators are dropped, and a warning message is logged.

    `Receivers` also function as AsyncIterator.
    """

    def __init__(self, **kwargs: AsyncIterator[Any]) -> None:
        """Create a `Select` instance.

        Args:
            **kwargs: sequence of async iterators
        """
        self._receivers = kwargs
        self._pending: Set[asyncio.Task[Any]] = set()

        for name, recv in self._receivers.items():
            # can replace __anext__() to anext() (Only Python 3.10>=)
            msg = recv.__anext__()  # pylint: disable=unnecessary-dunder-call
            self._pending.add(asyncio.create_task(msg, name=name))  # type: ignore

        self._ready_count = 0
        self._prev_ready_count = 0
        self._result: Dict[str, Optional[_Selected]] = {
            name: None for name in self._receivers
        }

    def __del__(self) -> None:
        """Cleanup any pending tasks."""
        for task in self._pending:
            task.cancel()

    async def ready(self) -> bool:
        """Wait until there is a message in any of the async iterators.

        Returns True if there is a message available, and False if all async
        iterators have closed.

        Returns:
            Boolean indicating whether there are further messages or not.
        """
        if self._ready_count > 0:
            if self._ready_count == self._prev_ready_count:
                dropped_names: List[str] = []
                for name, value in self._result.items():
                    if value is not None:
                        dropped_names.append(name)
                        self._result[name] = None
                self._ready_count = 0
                self._prev_ready_count = 0
                logger.warning(
                    "Select.ready() dropped data from async iterator(s): %s, "
                    "because no messages have been fetched since the last call to ready().",
                    dropped_names,
                )
            else:
                self._prev_ready_count = self._ready_count
                return True
        if len(self._pending) == 0:
            return False

        # once all the pending messages have been consumed, reset the
        # `_prev_ready_count` as well, and wait for new messages.
        self._prev_ready_count = 0

        done, self._pending = await asyncio.wait(
            self._pending, return_when=asyncio.FIRST_COMPLETED
        )
        for item in done:
            name = item.get_name()
            if isinstance(item.exception(), StopAsyncIteration):
                result = None
            else:
                result = item.result()
            self._ready_count += 1
            self._result[name] = _Selected(result)
            # if channel or AsyncIterator is closed
            # don't add a task for it again.
            if result is None:
                continue
            msg = self._receivers[  # pylint: disable=unnecessary-dunder-call
                name
            ].__anext__()
            self._pending.add(asyncio.create_task(msg, name=name))  # type: ignore
        return True

    def __getattr__(self, name: str) -> Optional[Any]:
        """Return the latest unread message from a AsyncIterator, if available.

        Args:
            name: Name of the channel.

        Returns:
            Latest unread message for the specified AsyncIterator, or None.

        Raises:
            KeyError: when the name was not specified when creating the Select
                instance.
        """
        result = self._result[name]
        if result is None:
            return result
        self._result[name] = None
        self._ready_count -= 1
        return result
