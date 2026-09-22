-- Band WezTerm tab bar / status plugin.
-- Install via wezterm.plugin.require + apply_to_config (see band-wezterm setup).
-- Lua only renders hex/values received over OSC — never recomputes identity hashes.
--
-- WezTerm runs only the first format-tab-title handler. Register Band via
-- apply_to_config early in your config (setup injects after config_builder).
--
-- Tab colors read WezTerm's durable pane user_vars (set by OSC from the agent
-- process). A parallel Lua cache is intentionally not used: it went stale after
-- stop/restart when mux.get_pane missed live panes.

local wezterm = require("wezterm")

local M = {}
local handlers_installed = false

-- Multi-segment room underline from band.agent.room_colors CSV.
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

local function pane_band_vars(pane)
  if pane == nil then
    return {}
  end
  if pane.user_vars ~= nil then
    return pane.user_vars
  end
  if pane.get_user_vars ~= nil then
    return pane:get_user_vars() or {}
  end
  return {}
end

local function install_handlers()
  if handlers_installed then
    return
  end
  handlers_installed = true

  -- Raise + switch to the Band workspace when the host emits `band.focus`.
  -- WezTerm has no CLI for workspace switch (#3542); OSC from a live pane is the
  -- supported workaround. Host prefers a default-workspace window so this is a
  -- no-op when Control already shares the active workspace.
  wezterm.on("user-var-changed", function(window, pane, name, value)
    if name == "band.focus" then
      window:perform_action(
        wezterm.action.SwitchToWorkspace { name = "band" },
        pane
      )
      window:focus()
    end
  end)

  wezterm.on("format-tab-title", function(tab, tabs, panes, config, hover, max_width)
    local pane = tab.active_pane
    local state = pane_band_vars(pane)
    local tab_title = tab.tab_title
    -- Explicit mux title wins for the Control host (Textual's process title is useless).
    if tab_title == "Control" then
      return { { Text = " ◆ Control " } }
    end

    local name = state["band.agent.name"]
    local initials = state["band.agent.initials"]
    if name == nil and initials == nil then
      local title = (tab_title ~= nil and tab_title ~= "" and tab_title)
        or pane.title
        or "shell"
      if title:find("band_wezterm") or title:find("Control") then
        return { { Text = " ◆ Control " } }
      end
      return { { Text = " " .. title .. " " } }
    end

    local color = state["band.agent.color"] or "#444444"
    local kind = state["band.agent.kind"] or "agent"
    local glyph = (kind == "human") and "●" or "■"
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

    -- Full agent name (truncated); harness stays on the Agents list, not the tab.
    local label = wezterm.truncate_right(name or initials or "?", math.max(4, (max_width or 20) - 6))

    local elements = {
      { Background = { Color = color } },
      { Foreground = { Color = "#ffffff" } },
      { Text = string.format(" %s %s %s ", glyph, label, presence) },
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

  -- Default WezTerm title is "[n/m] python3.x"; brand Band host windows instead.
  wezterm.on("format-window-title", function(tab, pane, tabs, panes, config)
    for _, t in ipairs(tabs) do
      if (t.tab_title or "") == "Control" then
        return "Band"
      end
      local active = t.active_pane
      local state = pane_band_vars(active)
      if state["band.agent.id"] ~= nil or state["band.agent.name"] ~= nil then
        return "Band"
      end
    end
  end)

  wezterm.on("update-status", function(window, pane)
    local state = pane_band_vars(pane)
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
end

function M.apply_to_config(config, _opts)
  install_handlers()
  return config
end

return M
