// Command scheduler-server 是调度层 gRPC 服务。
//
// 职责：任务调度、限流、重试。通过 HTTP 调用 Flask 服务层执行 DAG，
// 并把结果回填到任务状态。限流用令牌间隔实现，重试用指数退避。
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"sync"
	"time"

	"google.golang.org/grpc"

	pb "github.com/adgenie/scheduler/proto"
)

const (
	statusQueued  = "queued"
	statusRunning = "running"
	statusDone    = "done"
	statusFailed  = "failed"
)

type job struct {
	id      string
	req     *pb.ScheduleRequest
	status  string
	result  string
	retries int32
}

type server struct {
	pb.UnimplementedSchedulerServer

	mu       sync.Mutex
	jobs     map[string]*job
	queue    chan string
	nextID   int64
	rate     time.Duration // 每次调度最小间隔
	service  string        // Flask 服务地址
	retryMax int
	backoff  time.Duration

	dispatchMu  sync.Mutex
	lastDispatch time.Time
}

func newServer(serviceURL string, rate time.Duration, retryMax int, backoff time.Duration) *server {
	s := &server{
		jobs:     make(map[string]*job),
		queue:    make(chan string, 1024),
		rate:     rate,
		service:  serviceURL,
		retryMax: retryMax,
		backoff:  backoff,
	}
	go s.worker()
	return s
}

func (s *server) SchedulePipeline(ctx context.Context, req *pb.ScheduleRequest) (*pb.ScheduleResponse, error) {
	s.mu.Lock()
	s.nextID++
	id := fmt.Sprintf("job-%d", s.nextID)
	j := &job{id: id, req: req, status: statusQueued}
	s.jobs[id] = j
	s.mu.Unlock()

	s.queue <- id
	return &pb.ScheduleResponse{JobId: id, Status: statusQueued}, nil
}

func (s *server) GetJobStatus(ctx context.Context, req *pb.JobStatusRequest) (*pb.JobStatusResponse, error) {
	s.mu.Lock()
	j, ok := s.jobs[req.GetJobId()]
	s.mu.Unlock()
	if !ok {
		return nil, fmt.Errorf("job not found: %s", req.GetJobId())
	}
	return &pb.JobStatusResponse{
		JobId:   j.id,
		Status:  j.status,
		Result:  j.result,
		Retries: j.retries,
	}, nil
}

func (s *server) setStatus(id, status, result string, retries int32) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if j, ok := s.jobs[id]; ok {
		j.status = status
		j.result = result
		j.retries = retries
	}
}

// worker 从队列取任务，限流后调度执行，失败按指数退避重试。
func (s *server) worker() {
	for id := range s.queue {
		s.run(id)
	}
}

func (s *server) run(id string) {
	s.mu.Lock()
	j := s.jobs[id]
	s.mu.Unlock()
	if j == nil {
		return
	}
	s.setStatus(id, statusRunning, "", 0)

	var lastErr error
	for attempt := 0; attempt <= s.retryMax; attempt++ {
		if attempt > 0 {
			// 指数退避
			time.Sleep(s.backoff * time.Duration(1<<(attempt-1)))
			s.setStatus(id, statusRunning, "", int32(attempt))
		}
		s.waitRateLimit()
		body, err := s.dispatch(j.req)
		if err == nil {
			s.setStatus(id, statusDone, body, int32(attempt))
			return
		}
		lastErr = err
	}
	s.setStatus(id, statusFailed, lastErr.Error(), int32(s.retryMax))
}

// waitRateLimit 保证两次调度之间至少间隔 s.rate。
func (s *server) waitRateLimit() {
	s.dispatchMu.Lock()
	defer s.dispatchMu.Unlock()
	if elapsed := time.Since(s.lastDispatch); elapsed < s.rate {
		time.Sleep(s.rate - elapsed)
	}
	s.lastDispatch = time.Now()
}

// dispatch 调用 Flask 服务层 /pipeline。
func (s *server) dispatch(req *pb.ScheduleRequest) (string, error) {
	payload := map[string]string{
		"listing_id":         req.GetListingId(),
		"copy_text":          req.GetCopyText(),
		"profile_version":    req.GetProfileVersion(),
		"copy_version":       req.GetCopyVersion(),
		"rubric_version":     req.GetRubricVersion(),
		"knowledge_version":  req.GetKnowledgeVersion(),
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return "", err
	}
	client := &http.Client{Timeout: 60 * time.Second}
	resp, err := client.Post(s.service+"/pipeline", "application/json", bytes.NewReader(raw))
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("pipeline returned status %d", resp.StatusCode)
	}
	var out bytes.Buffer
	if _, err := out.ReadFrom(resp.Body); err != nil {
		return "", err
	}
	return out.String(), nil
}

func main() {
	serviceURL := getEnv("ADGENIE_SERVICE_URL", "http://127.0.0.1:5000")
	addr := getEnv("ADGENIE_GRPC_ADDR", ":50051")
	lis, err := net.Listen("tcp", addr)
	if err != nil {
		log.Fatalf("listen: %v", err)
	}
	srv := newServer(serviceURL, 500*time.Millisecond, 3, 1*time.Second)
	gs := grpc.NewServer()
	pb.RegisterSchedulerServer(gs, srv)
	log.Printf("scheduler gRPC listening on %s -> %s", addr, serviceURL)
	if err := gs.Serve(lis); err != nil {
		log.Fatalf("serve: %v", err)
	}
}

func getEnv(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok {
		return v
	}
	return fallback
}
