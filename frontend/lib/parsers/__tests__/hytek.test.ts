import { describe, it } from 'node:test';
import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { parseHytekResults } from '../hytek';
import type { ParsedMeet, ParsedEvent, ParsedResult } from '../hytek';

const fixturePath = join(__dirname, '..', 'fixtures', 'sample-hytek.txt');

function loadFixture(): string {
  return readFileSync(fixturePath, 'utf-8');
}

describe('parseHytekResults', () => {
  describe('meet name parsing', () => {
    it('should extract the meet name from header', () => {
      const text = loadFixture();
      const result = parseHytekResults(text);
      assert.strictEqual(result.meetName, '56th SNAG Swimming Championships 2026');
    });

    it('should return empty meet name for empty input', () => {
      const result = parseHytekResults('');
      assert.strictEqual(result.meetName, '');
    });

    it('should return empty events for empty input', () => {
      const result = parseHytekResults('');
      assert.deepStrictEqual(result.events, []);
    });
  });

  describe('event header parsing', () => {
    it('should parse all events from fixture', () => {
      const result = parseHytekResults(loadFixture());
      assert.strictEqual(result.events.length, 5);
    });

    it('should parse event numbers correctly', () => {
      const result = parseHytekResults(loadFixture());
      const eventNumbers = result.events.map((e) => e.eventNumber);
      assert.deepStrictEqual(eventNumbers, [1, 2, 3, 4, 5]);
    });

    it('should parse event names correctly', () => {
      const result = parseHytekResults(loadFixture());
      assert.strictEqual(result.events[0].eventName, 'Boys 13-14 200 LC Meter IM');
      assert.strictEqual(result.events[1].eventName, 'Girls 13-14 100 LC Meter Freestyle');
      assert.strictEqual(result.events[2].eventName, 'Boys 15-17 50 LC Meter Backstroke');
      assert.strictEqual(result.events[3].eventName, 'Girls 15-17 200 LC Meter Breaststroke');
      assert.strictEqual(result.events[4].eventName, 'Boys 11-12 100 LC Meter Butterfly');
    });

    it('should parse a single event correctly', () => {
      const text = `                        Test Meet 2026

Event 1  Boys 13-14 200 LC Meter IM
===============================================================================
    Name                    Age Team                    Seed Time Finals Time
===============================================================================
  1 WU, Dylan Jiaxu          14 Pacific Swimming        2:22.10   2:18.62
`;
      const result = parseHytekResults(text);
      assert.strictEqual(result.events.length, 1);
      assert.strictEqual(result.events[0].eventNumber, 1);
    });
  });

  describe('individual result parsing', () => {
    let meet: ParsedMeet;

    it('should load fixture and parse', () => {
      meet = parseHytekResults(loadFixture());
      assert.ok(meet.events.length > 0);
    });

    it('should parse placement correctly', () => {
      meet = parseHytekResults(loadFixture());
      const event1 = meet.events[0];
      // First placed swimmer
      assert.strictEqual(event1.results[0].placement, 1);
      assert.strictEqual(event1.results[1].placement, 2);
      assert.strictEqual(event1.results[5].placement, 6);
    });

    it('should parse swimmer name correctly', () => {
      meet = parseHytekResults(loadFixture());
      const event1 = meet.events[0];
      assert.strictEqual(event1.results[0].swimmerName, 'WU, Dylan Jiaxu');
      assert.strictEqual(event1.results[1].swimmerName, 'TAN, Wei Ming');
    });

    it('should parse age correctly', () => {
      meet = parseHytekResults(loadFixture());
      const event1 = meet.events[0];
      assert.strictEqual(event1.results[0].age, 14);
      assert.strictEqual(event1.results[1].age, 13);
    });

    it('should parse team correctly', () => {
      meet = parseHytekResults(loadFixture());
      const event1 = meet.events[0];
      assert.strictEqual(event1.results[0].team, 'Pacific Swimming');
      assert.strictEqual(event1.results[1].team, 'AquaTech Swimming');
    });

    it('should parse seed time correctly', () => {
      meet = parseHytekResults(loadFixture());
      const event1 = meet.events[0];
      assert.strictEqual(event1.results[0].seedTime, '2:22.10');
      assert.strictEqual(event1.results[1].seedTime, '2:24.55');
    });

    it('should parse finals time correctly', () => {
      meet = parseHytekResults(loadFixture());
      const event1 = meet.events[0];
      assert.strictEqual(event1.results[0].finalsTime, '2:18.62');
      assert.strictEqual(event1.results[1].finalsTime, '2:20.14');
    });

    it('should parse sub-minute times without colon', () => {
      meet = parseHytekResults(loadFixture());
      const event2 = meet.events[1];
      assert.strictEqual(event2.results[0].finalsTime, '58.92');
      assert.strictEqual(event2.results[1].finalsTime, '59.45');
    });

    it('should parse results count per event', () => {
      meet = parseHytekResults(loadFixture());
      // Event 1: 6 placed + 2 DQ = 8
      assert.strictEqual(meet.events[0].results.length, 8);
      // Event 2: 5 placed + 1 DQ = 6
      assert.strictEqual(meet.events[1].results.length, 6);
    });
  });

  describe('DQ detection and reason extraction', () => {
    let meet: ParsedMeet;

    it('should detect DQ entries', () => {
      meet = parseHytekResults(loadFixture());
      const event1 = meet.events[0];
      const dqResults = event1.results.filter((r) => r.isDQ);
      assert.strictEqual(dqResults.length, 2);
    });

    it('should set null placement for DQ entries', () => {
      meet = parseHytekResults(loadFixture());
      const event1 = meet.events[0];
      const dqResults = event1.results.filter((r) => r.isDQ);
      for (const dq of dqResults) {
        assert.strictEqual(dq.placement, null);
      }
    });

    it('should set null finals time for DQ entries', () => {
      meet = parseHytekResults(loadFixture());
      const event1 = meet.events[0];
      const dqResults = event1.results.filter((r) => r.isDQ);
      for (const dq of dqResults) {
        assert.strictEqual(dq.finalsTime, null);
      }
    });

    it('should extract DQ reason', () => {
      meet = parseHytekResults(loadFixture());
      const event1 = meet.events[0];
      const dqResults = event1.results.filter((r) => r.isDQ);
      assert.strictEqual(dqResults[0].dqReason, 'Alternating Kick - Loss of count');
      assert.strictEqual(dqResults[1].dqReason, 'One hand touch - Butterfly');
    });

    it('should detect DQ in event 2', () => {
      meet = parseHytekResults(loadFixture());
      const event2 = meet.events[1];
      const dqResults = event2.results.filter((r) => r.isDQ);
      assert.strictEqual(dqResults.length, 1);
      assert.strictEqual(dqResults[0].swimmerName, 'TAN, Hui Wen');
      assert.strictEqual(dqResults[0].dqReason, 'False start');
    });

    it('should preserve seed time for DQ entries', () => {
      meet = parseHytekResults(loadFixture());
      const event1 = meet.events[0];
      const dqResults = event1.results.filter((r) => r.isDQ);
      assert.strictEqual(dqResults[0].seedTime, '2:30.15');
    });
  });

  describe('DNS and DNF handling', () => {
    let meet: ParsedMeet;

    it('should detect DNS entries', () => {
      meet = parseHytekResults(loadFixture());
      const event3 = meet.events[2]; // Boys 15-17 50 LC Backstroke
      const dnsResults = event3.results.filter((r) => r.dqReason === 'DNS');
      assert.strictEqual(dnsResults.length, 1);
      assert.strictEqual(dnsResults[0].swimmerName, 'LOW, Ming Han');
      assert.strictEqual(dnsResults[0].isDQ, true);
      assert.strictEqual(dnsResults[0].finalsTime, null);
    });

    it('should detect DNF entries', () => {
      meet = parseHytekResults(loadFixture());
      const event4 = meet.events[3]; // Girls 15-17 200 LC Breaststroke
      const dnfResults = event4.results.filter((r) => r.dqReason === 'DNF');
      assert.strictEqual(dnfResults.length, 1);
      assert.strictEqual(dnfResults[0].swimmerName, 'ONG, Jia Qi');
      assert.strictEqual(dnfResults[0].isDQ, true);
      assert.strictEqual(dnfResults[0].finalsTime, null);
    });

    it('should handle missing seed time for DNS', () => {
      meet = parseHytekResults(loadFixture());
      const event3 = meet.events[2];
      const dnsResult = event3.results.find((r) => r.dqReason === 'DNS');
      // DNS entry in fixture has no seed time
      assert.ok(dnsResult);
    });
  });

  describe('edge cases', () => {
    it('should handle empty string input', () => {
      const result = parseHytekResults('');
      assert.strictEqual(result.meetName, '');
      assert.deepStrictEqual(result.events, []);
    });

    it('should handle whitespace-only input', () => {
      const result = parseHytekResults('   \n\n  \n  ');
      assert.strictEqual(result.meetName, '');
      assert.deepStrictEqual(result.events, []);
    });

    it('should handle input with header but no events', () => {
      const result = parseHytekResults('Some Meet Name 2026\nResults - Session 1\n');
      assert.strictEqual(result.meetName, 'Some Meet Name 2026');
      assert.deepStrictEqual(result.events, []);
    });

    it('should handle malformed event block with no results', () => {
      const text = `Test Meet

Event 1  Boys 13-14 200 LC Meter IM
===============================================================================
    Name                    Age Team                    Seed Time Finals Time
===============================================================================
`;
      const result = parseHytekResults(text);
      assert.strictEqual(result.events.length, 1);
      assert.strictEqual(result.events[0].results.length, 0);
    });
  });

  describe('integration test with full fixture', () => {
    it('should parse the entire fixture file without errors', () => {
      const text = loadFixture();
      const result = parseHytekResults(text);
      assert.ok(result.meetName.length > 0);
      assert.strictEqual(result.events.length, 5);

      // Verify all events have results
      for (const event of result.events) {
        assert.ok(event.results.length > 0, `Event ${event.eventNumber} should have results`);
      }
    });

    it('should count total results across all events', () => {
      const text = loadFixture();
      const result = parseHytekResults(text);
      const totalResults = result.events.reduce((sum, e) => sum + e.results.length, 0);
      // 8 + 6 + 7 + 6 + 7 = 34
      assert.ok(totalResults > 30, `Expected at least 30 total results, got ${totalResults}`);
    });

    it('should have consistent data types across all results', () => {
      const text = loadFixture();
      const result = parseHytekResults(text);
      for (const event of result.events) {
        for (const r of event.results) {
          assert.strictEqual(typeof r.swimmerName, 'string');
          assert.strictEqual(typeof r.age, 'number');
          assert.strictEqual(typeof r.team, 'string');
          assert.strictEqual(typeof r.isDQ, 'boolean');
          assert.ok(r.placement === null || typeof r.placement === 'number');
          assert.ok(r.seedTime === null || typeof r.seedTime === 'string');
          assert.ok(r.finalsTime === null || typeof r.finalsTime === 'string');
          assert.ok(r.dqReason === null || typeof r.dqReason === 'string');
        }
      }
    });
  });
});
