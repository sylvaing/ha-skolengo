"""To-do lists of the Skolengo integration: the homework, which can be ticked as done."""

from __future__ import annotations

from dataclasses import replace

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import SkolengoConfigEntry
from .api import SkolengoAuthError, SkolengoError, SkolengoForbiddenError
from .api.const import SERVICE_HOMEWORK
from .const import DOMAIN
from .entity import SkolengoStudentEntity
from .homework import homework_summary

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: SkolengoConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """One homework list per student whose school grants homework."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        SkolengoHomeworkTodo(coordinator, data.student)
        for data in coordinator.data.students.values()
        if SERVICE_HOMEWORK in data.services
    )


class SkolengoHomeworkTodo(SkolengoStudentEntity, TodoListEntity):
    """The homework of a student; ticking an item marks it done in the ENT."""

    # Only the status of an item can change (the text belongs to the teacher).
    _attr_supported_features = TodoListEntityFeature.UPDATE_TODO_ITEM

    def __init__(self, coordinator, student) -> None:
        """Homework list of one student."""
        super().__init__(coordinator, student, SERVICE_HOMEWORK, "homework")
        self._school_id = student.school.id if student.school else None

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """One item per homework, by due date."""
        data = self.student_data
        if data is None or data.homework is None:
            return None
        return [
            TodoItem(
                uid=hw.id,
                summary=homework_summary(hw),
                description=hw.text if hw.text != hw.title else None,
                due=dt_util.as_local(hw.due),
                status=TodoItemStatus.COMPLETED if hw.done else TodoItemStatus.NEEDS_ACTION,
            )
            for hw in data.homework
        ]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Only the status can change: it is sent to the ENT."""
        data = self.student_data
        homework = data.homework if data and data.homework else []
        current = next((hw for hw in homework if hw.id == item.uid), None)
        if current is None or self._school_id is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="homework_not_found",
                translation_placeholders={"uid": str(item.uid)},
            )
        done = item.status == TodoItemStatus.COMPLETED
        if done == current.done:
            return
        try:
            await self.coordinator.client.async_set_homework_done(
                self._student_id, self._school_id, current.id, done
            )
        except SkolengoForbiddenError as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="homework_forbidden") from err
        except SkolengoAuthError as err:
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="auth_expired") from err
        except SkolengoError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="homework_update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        # The ENT accepted it: update the local copy at once instead of re-reading everything.
        data.homework = [replace(hw, done=done) if hw.id == current.id else hw for hw in data.homework]
        self.coordinator.async_update_listeners()
