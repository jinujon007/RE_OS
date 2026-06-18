// RE_OS — k6 Baseline Load Test (T-1249)
// 50 VUs with staged ramp-up; p95 <200ms; failure rate <1%
// Endpoints: health/live + health + status (read-only mix)
import http from 'k6/http';
import { check } from 'k6';

export const options = {
  stages: [
    { duration: '10s', target: 10 },   // warm-up: 10 VUs
    { duration: '20s', target: 25 },   // ramp to 25 VUs
    { duration: '20s', target: 50 },   // ramp to target 50 VUs
    { duration: '10s', target: 50 },   // sustained peak
  ],
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<200'],
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
