-- Atomically check if timer is expired and delete it if so
-- This prevents multiple timer workers from firing the same timer
--
-- KEYS[1]: timer metadata key
-- ARGV[1]: current_time (unix timestamp as float)
--
-- Returns: metadata hash if expired and deleted, nil otherwise

local key = KEYS[1]
local current_time = tonumber(ARGV[1])

-- Get all timer metadata
local metadata = redis.call('HGETALL', key)
if #metadata == 0 then
    return nil  -- Timer already deleted by another worker
end

-- Parse metadata to find wake_time
local wake_time = nil
for i = 1, #metadata, 2 do
    if metadata[i] == 'wake_time' then
        wake_time = tonumber(metadata[i+1])
        break
    end
end

-- Check if wake_time exists and timer is expired
if wake_time and wake_time <= current_time then
    -- Timer expired! Delete it atomically
    redis.call('DEL', key)
    -- Return the metadata so the worker knows what to do
    return metadata
else
    -- Timer not expired yet, or invalid
    return nil
end
