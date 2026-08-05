-- LunaUX Next local API client.
-- Use only in environments where you are authorized to inspect the target bytecode.

assert(request, "HTTP request function missing")
assert(getscriptbytecode, "getscriptbytecode function missing")

local HttpService = game:GetService("HttpService")
local base64Encode = (crypt and crypt.base64 and crypt.base64.encode) or base64encode
assert(base64Encode, "Base64 encoder missing")

local API_BASE = "http://127.0.0.1:8000/v1"

local function isSupportedScript(instance: Instance): boolean
    if instance:IsA("LocalScript") or instance:IsA("ModuleScript") then
        return true
    end
    return instance:IsA("Script") and instance.RunContext == Enum.RunContext.Client
end

local function callApi(path: string, payload: {[string]: any}): string
    local response = request({
        Url = API_BASE .. path,
        Method = "POST",
        Headers = { ["Content-Type"] = "application/json" },
        Body = HttpService:JSONEncode(payload),
    })

    if response.StatusCode < 200 or response.StatusCode >= 300 then
        return string.format(
            "--[[ LunaUX Next API error (HTTP %s)\n%s\n]]",
            tostring(response.StatusCode),
            tostring(response.Body)
        )
    end

    local ok, decoded = pcall(HttpService.JSONDecode, HttpService, response.Body)
    if not ok or type(decoded) ~= "table" or type(decoded.result) ~= "string" then
        return "--[[ LunaUX Next returned an invalid response. ]]"
    end
    return decoded.result
end

local function readBytecode(scriptInstance: Instance): (boolean, string)
    if typeof(scriptInstance) ~= "Instance" then
        return false, "Expected a script Instance"
    end
    if not isSupportedScript(scriptInstance) then
        return false, "Only client-visible Script, LocalScript, and ModuleScript bytecode is supported"
    end

    local ok, result = pcall(getscriptbytecode, scriptInstance)
    if not ok then
        return false, tostring(result)
    end
    if type(result) ~= "string" or result == "" then
        return false, "Bytecode is empty or unavailable"
    end
    return true, result
end

local function process(scriptInstance: Instance, endpoint: string, options: {[string]: any}?): string
    local ok, bytecodeOrError = readBytecode(scriptInstance)
    if not ok then
        return "--[[ " .. bytecodeOrError .. " ]]"
    end

    local payload = {
        bytecode = base64Encode(bytecodeOrError),
        filename = scriptInstance.Name,
    }
    if options ~= nil then
        payload.options = options
    end
    return callApi(endpoint, payload)
end

if getgenv then
    getgenv().decompile = function(scriptInstance: Instance, options: {[string]: any}?): string
        return process(scriptInstance, "/decompile", options or {})
    end

    getgenv().disassemble = function(scriptInstance: Instance): string
        return process(scriptInstance, "/disassemble", nil)
    end
end
