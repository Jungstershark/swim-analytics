export interface ParsedResult {
  placement: number | null;
  swimmerName: string;
  age: number;
  team: string;
  seedTime: string | null;
  finalsTime: string | null;
  isDQ: boolean;
  dqReason: string | null;
}

export interface ParsedEvent {
  eventNumber: number;
  eventName: string;
  results: ParsedResult[];
}

export interface ParsedMeet {
  meetName: string;
  events: ParsedEvent[];
}

/**
 * Parse a HY-TEK Meet Manager results text into structured data.
 */
export function parseHytekResults(text: string): ParsedMeet {
  if (!text || text.trim().length === 0) {
    return { meetName: '', events: [] };
  }

  const lines = text.split('\n');
  const meetName = parseMeetName(lines);
  const events = parseEvents(lines);

  return { meetName, events };
}

/**
 * Extract the meet name from the header lines.
 * The meet name is typically the first non-empty line.
 */
function parseMeetName(lines: string[]): string {
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.length > 0 && !trimmed.startsWith('Results') && !trimmed.startsWith('Event')) {
      return trimmed;
    }
  }
  return '';
}

/**
 * Split text into event blocks and parse each one.
 */
function parseEvents(lines: string[]): ParsedEvent[] {
  const events: ParsedEvent[] = [];
  const eventHeaderRegex = /^Event\s+(\d+)\s+(.+)$/;

  let currentEventStart = -1;

  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    const match = trimmed.match(eventHeaderRegex);

    if (match) {
      // If we were already tracking an event, parse the previous block
      if (currentEventStart >= 0) {
        const event = parseEventBlock(lines, currentEventStart, i);
        if (event) events.push(event);
      }
      currentEventStart = i;
    }
  }

  // Parse the last event block
  if (currentEventStart >= 0) {
    const event = parseEventBlock(lines, currentEventStart, lines.length);
    if (event) events.push(event);
  }

  return events;
}

/**
 * Parse a single event block from startLine to endLine.
 */
function parseEventBlock(lines: string[], startLine: number, endLine: number): ParsedEvent | null {
  const headerLine = lines[startLine].trim();
  const headerMatch = headerLine.match(/^Event\s+(\d+)\s+(.+)$/);

  if (!headerMatch) return null;

  const eventNumber = parseInt(headerMatch[1], 10);
  const eventName = headerMatch[2].trim();
  const results: ParsedResult[] = [];

  // Result line pattern:
  // Placed:  "  1 NAME, First              14 Team Name            1:23.45   1:22.10"
  // DQ/DNS:  "  --- NAME, First            14 Team Name            1:23.45      DQ"
  const resultLineRegex = /^\s*(---|\d+)\s+(\S+(?:,\s*\S+(?:\s+\S+)*))\s+(\d{1,2})\s+(.+?)\s{2,}(\S+)?\s+(\S+)\s*$/;

  for (let i = startLine + 1; i < endLine; i++) {
    const line = lines[i];

    // Skip separator lines and header lines
    if (line.trim().startsWith('===') || line.trim().startsWith('Name') || line.trim().length === 0) {
      continue;
    }

    const match = line.match(resultLineRegex);
    if (match) {
      const placementStr = match[1];
      const swimmerName = match[2].trim();
      const age = parseInt(match[3], 10);
      const team = match[4].trim();
      const seedTimeRaw = match[5] || null;
      const finalsTimeRaw = match[6];

      const isDQ = placementStr === '---';
      const isDNS = finalsTimeRaw === 'DNS';
      const isDNF = finalsTimeRaw === 'DNF';
      const isDisqualified = finalsTimeRaw === 'DQ';

      let dqReason: string | null = null;

      // If DQ, look for reason on the next line
      if (isDisqualified && i + 1 < endLine) {
        const nextLine = lines[i + 1].trim();
        // The DQ reason line is indented text that doesn't match a result pattern
        if (nextLine.length > 0 && !nextLine.startsWith('===') && !nextLine.match(resultLineRegex) && !nextLine.startsWith('Event')) {
          dqReason = nextLine;
        }
      }

      const placement = isDQ ? null : parseInt(placementStr, 10);
      const seedTime = seedTimeRaw && seedTimeRaw !== '' ? seedTimeRaw : null;
      const finalsTime = (isDisqualified || isDNS || isDNF) ? null : finalsTimeRaw;

      results.push({
        placement: isNaN(placement as number) ? null : placement,
        swimmerName,
        age,
        team,
        seedTime,
        finalsTime,
        isDQ: isDisqualified || isDNS || isDNF,
        dqReason: isDNS ? 'DNS' : isDNF ? 'DNF' : dqReason,
      });
    }
  }

  return { eventNumber, eventName, results };
}
