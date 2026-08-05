-- LunaUX Next local API client
-- Requires an authorized environment that provides request, getscriptbytecode,
-- and either base64encode or crypt.base64.encode.

assert(request, "http request function missing")
assert(getscriptbytecode, "getscriptbytecode function missing")

local base64_encoder = (crypt and crypt.base64 and crypt.base64.encode) or base64encode
assert(base64_encoder, "base64encode function missing")

local http = game:GetService("HttpService")
local environment = getgenv and getgenv() or _G
local apiBaseUrl = environment.LUNAUX_API_URL or "http://127.0.0.1:8000"

environment.LUNAUX_OPTIONS = environment.LUNAUX_OPTIONS or {
    Semicolons = false,
    StringInterpolation = true,
    UpvalueComment = true,
    ShowLineDefined = true,
    ShowFunctionId = false,
    PreserveForStep = false,
    UseIfExpression = true,
    InlineSingleUseTemporaries = true,
    MaxOutputCharacters = 4000000,
}

local function apiRequest(bytecode, branch, scriptName, options)
    local payload = {
        bytecode = base64_encoder(bytecode),
        filename = scriptName,
    }

    if options then
        payload.options = options
    end

    local response = request({
        Url = apiBaseUrl .. "/" .. branch,
        Method = "POST",
        Headers = {
            ["Content-Type"] = "application/json",
        },
        Body = http:JSONEncode(payload),
    })

    if response.StatusCode ~= 200 then
        return `--[[ Server error (HTTP {response.StatusCode}):\n\t{response.Body}\n]]`
    end

    return response.Body
end

local function isValidScript(scriptInstance: BaseScript)
    return
        (scriptInstance.ClassName == "Script" and scriptInstance.RunContext == Enum.RunContext.Client)
        or scriptInstance.ClassName == "LocalScript"
        or scriptInstance.ClassName == "ModuleScript"
end

environment.decompile = function(scriptPath: BaseScript)
    if typeof(scriptPath) ~= "Instance" then
        return "-- Invalid argument #1 to 'decompile' (Instance expected)"
    end
    if not isValidScript(scriptPath) then
        return "-- Server scripts are IMPOSSIBLE to decompile"
    end

    local ok, bytecode = pcall(getscriptbytecode, scriptPath)
    if not ok then
        return `--[[ Failed to get script bytecode:\n\t{bytecode}\n]]`
    end
    if type(bytecode) ~= "string" then
        return `--[[ Failed to get script bytecode, string type expected got {type(bytecode)} ]]`
    end
    if bytecode == "" then
        return "-- Empty bytecode"
    end

    return apiRequest(bytecode, "decompile", scriptPath.Name, environment.LUNAUX_OPTIONS)
end

environment.disassemble = function(scriptPath: BaseScript)
    if typeof(scriptPath) ~= "Instance" then
        return "-- Invalid argument #1 to 'disassemble' (Instance expected)"
    end
    if not isValidScript(scriptPath) then
        return "-- Server scripts are IMPOSSIBLE to disassemble"
    end

    local ok, bytecode = pcall(getscriptbytecode, scriptPath)
    if not ok then
        return `--[[ Failed to get script bytecode:\n\t{bytecode}\n]]`
    end
    if type(bytecode) ~= "string" then
        return `--[[ Failed to get script bytecode, string type expected got {type(bytecode)} ]]`
    end
    if bytecode == "" then
        return "-- Empty bytecode"
    end

    return apiRequest(bytecode, "disassemble", scriptPath.Name)
end
