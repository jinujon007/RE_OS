// RE_OS — k6 CI Baseline Load Test (T-1249, recalibrated T-1288)
// 20 VU CI baseline (gentle ramp for CI environments)
// Production benchmark (target: 100 VU) not yet defined — see docs/operations.md
// Endpoints: health/live + health + status (read-only mix)
import http from 'k6/http';
import { check } from 'k6';

export const options = {
  tags: {
    environment: __ENV.K6_ENV || 'ci',
    test_type: 'baseline',
    test_name: 'ci_baseline_20vu',
  },
  stages: [
    { duration: '10s', target: 10 },   // warm-up: 10 VUs
    { duration: '30s', target: 20 },   // ramp to CI baseline 20 VUs
    { duration: '10s', target: 0 },    // cooldown
  ],
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8050';
const API_KEY = __ENV.DASHBOARD_API_KEY || '';

const params = {
  headers: {
    'X-API-Key': API_KEY,
  },
  timeout: '10s',
};

const endpoints = [
  { url: '/api/v1/health/live', method: 'GET' },
  { url: '/api/v1/health', method: 'GET' },
  { url: '/api/v1/status', method: 'GET' },
];

export default function () {
  const ep = endpoints[Math.floor(Math.random() * endpoints.length)];

  const resp = http.get(`${BASE_URL}${ep.url}`, params);

  check(resp, {
    'status is 200': (r) => r.status === 200,
  });
}
