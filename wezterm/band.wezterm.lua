-- Band WezTerm tab bar / status (INT-1496).
-- From ~/.wezterm.lua:
--   dofile("/absolute/path/to/band-wezterm/wezterm/band.wezterm.lua")
-- Lua only renders hex/values received over OSC — never recomputes identity hashes.

local wezterm = require("wezterm")

local pane_state = {}

local function ensure(pane_id)
  if pane_state[pane_id] == nil then
    pane_state[pane_id] = {}
  end
  return pane_state[pane_id]
end

local function forget_closed_panes()
  for pane_id in pairs(pane_state) do
    if wezterm.mux.get_pane(pane_id) == nil then
      pane_state[pane_id] = nil
    end
  end
end

-- No repaint is requested here: the Window object has no invalidate method, and
-- the tab bar plus update-status are re-evaluated on the next redraw anyway
-- (at most status_update_interval later).
wezterm.on("user-var-changed", function(window, pane, name, value)
  if string.sub(name, 1, 5) ~= "band." then
    return
  end
  forget_closed_panes()
  ensure(pane:pane_id())[name] = value
end)

-- Multi-segment room underline: stacked background-colored cells from
-- band.agent.room_colors. If a host build can't render zero-width stacks
-- cleanly, fall back to "most recently active room wins the whole underline"
-- (first color in the list).
local function room_underline_segments(room_colors_csv)
  local segments = {}
  if room_colors_csv == nil or room_colors_csv == "" then
    return segments
  end
  for color in string.gmatch(room_colors_csv, "([^,]+)") do
    table.insert(segments, { Background = { Color = color } })
    table.insert(segments, { Text = "▁" })
  end
  table.insert(segments, "ResetAttributes")
  return segments
end

wezterm.on("format-tab-title", function(tab, tabs, panes, config, hover, max_width)
  local pane = tab.active_pane
  local state = pane_state[pane.pane_id] or {}
  local initials = state["band.agent.initials"]
  if initials == nil then
    -- Control tab / plain shell — no Band agent chrome.
    local title = pane.title or "shell"
    if title:find("band_wezterm") or title:find("Control") then
      return { { Text = " ◆ Control " } }
    end
    return { { Text = " " .. title .. " " } }
  end

  local color = state["band.agent.color"] or "#444444"
  local kind = state["band.agent.kind"] or "agent"
  local glyph = (kind == "human") and "●" or "■"
  local harness = state["band.agent.harness"]
  local harness_bit = harness and (" " .. harness) or ""
  local status = state["band.agent.status"]
  local runtime = state["band.agent.runtime"]
  local presence = "·"
  if runtime == "error" then
    presence = "!"
  elseif runtime == "running" or status == "online" then
    presence = "●"
  elseif status == "offline" then
    presence = "○"
  end

  local elements = {
    { Background = { Color = color } },
    { Foreground = { Color = "#ffffff" } },
    { Text = string.format(" %s %s%s %s ", glyph, initials, harness_bit, presence) },
    "ResetAttributes",
  }

  local underline = room_underline_segments(state["band.agent.room_colors"])
  if #underline == 0 and state["band.room.color"] then
    underline = room_underline_segments(state["band.room.color"])
  end
  for _, part in ipairs(underline) do
    table.insert(elements, part)
  end
  return elements
end)

wezterm.on("update-status", function(window, pane)
  local state = pane_state[pane:pane_id()] or {}
  local slug = state["band.room.slug"] or state["band.room.name"]
  if slug then
    local color = state["band.room.color"] or "#666666"
    window:set_right_status(wezterm.format({
      { Foreground = { Color = color } },
      { Text = " room:" .. slug .. " " },
    }))
  else
    window:set_right_status("")
  end
end)

return {}
