from __future__ import annotations

from collections.abc import Callable


def _arithmetic(seed: int) -> str:
    return f"""local seed = {seed}
local function calculate(value)
    local x = value * 3 + 7
    local y = x // 2
    return (y % 19) + (x ^ 2 % 23)
end
print(calculate(seed))
"""


def _conditional(seed: int) -> str:
    return f"""local seed = {seed}
local function classify(value)
    if value % 5 == 0 then
        return "five", value // 5
    elseif value % 2 == 0 then
        return "even", value + 2
    else
        return "odd", value - 1
    end
end
local kind, value = classify(seed)
print(kind, value)
"""


def _while_loop(seed: int) -> str:
    limit = seed % 9 + 4
    return f"""local limit = {limit}
local total = 0
local index = 0
while index < limit do
    index += 1
    if index % 3 == 0 then
        continue
    end
    total += index
    if total > 40 then
        break
    end
end
print(index, total)
"""


def _repeat_loop(seed: int) -> str:
    start = seed % 17 + 1
    return f"""local value = {start}
local steps = 0
repeat
    value = (value * 3 + 1) % 97
    steps += 1
until value % 7 == 0 or steps >= 12
print(value, steps)
"""


def _numeric_for(seed: int) -> str:
    limit = seed % 12 + 3
    return f"""local total = 0
for index = 1, {limit} do
    total += index * ((index % 3) + 1)
end
print(total)
"""


def _generic_for(seed: int) -> str:
    values = ", ".join(str((seed + index * 7) % 31) for index in range(6))
    return f"""local values = {{{values}}}
local total = 0
for index, value in ipairs(values) do
    total += index * value
end
print(total)
"""


def _closure(seed: int) -> str:
    bias = seed % 13
    return f"""local bias = {bias}
local function makeCounter(start)
    local value = start
    return function(step)
        value += step + bias
        return value
    end
end
local counter = makeCounter({seed % 11})
print(counter(1), counter(2), counter(3))
"""


def _multret(seed: int) -> str:
    return f"""local function summarize(first, ...)
    local total = first
    local count = select("#", ...)
    for _, value in ipairs({{...}}) do
        total += value
    end
    return total, count
end
local total, count = summarize({seed % 19}, 2, 3, 5, 7)
print(total, count)
"""


def _tables(seed: int) -> str:
    return f"""local record = {{
    Name = "case-{seed}",
    Stats = {{
        Score = {seed % 101},
        Enabled = {str(seed % 2 == 0).lower()},
    }},
    {seed % 17},
    {(seed * 3) % 29},
}}
record.Stats.Score += record[1]
print(record.Name, record.Stats.Score, record[2])
"""


def _strings(seed: int) -> str:
    return f"""local prefix = "seed"
local value = {seed}
local text = prefix .. ":" .. tostring(value)
local upper = string.upper(string.sub(text, 1, 4))
print(upper, #text, string.find(text, ":") ~= nil)
"""


def _recursion(seed: int) -> str:
    value = seed % 8 + 2
    return f"""local function factorial(value)
    if value <= 1 then
        return 1
    end
    return value * factorial(value - 1)
end
print(factorial({value}))
"""


def _boolean(seed: int) -> str:
    return f"""local value = {seed}
local left = value % 2 == 0
local right = value % 3 == 0
local selected = (left and not right) or (right and value > 10)
print(selected, left, right)
"""


def _method(seed: int) -> str:
    return f"""local accumulator = {{value = {seed % 17}}}
function accumulator:add(amount)
    self.value += amount
    return self.value
end
print(accumulator:add(2), accumulator:add(5))
"""


def _table_function(seed: int) -> str:
    return f"""local operations = {{
    apply = function(value)
        return value * 2 + {seed % 9}
    end,
}}
print(operations.apply({seed % 23}))
"""


TEMPLATES: tuple[tuple[str, Callable[[int], str]], ...] = (
    ("arithmetic", _arithmetic),
    ("conditional", _conditional),
    ("while", _while_loop),
    ("repeat", _repeat_loop),
    ("numeric-for", _numeric_for),
    ("generic-for", _generic_for),
    ("closure", _closure),
    ("multret", _multret),
    ("tables", _tables),
    ("strings", _strings),
    ("recursion", _recursion),
    ("boolean", _boolean),
    ("method", _method),
    ("table-function", _table_function),
)
