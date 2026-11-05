// Command scheduler-client 是调度层 gRPC 客户端示例。
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	pb "github.com/adgenie/scheduler/proto"
)

func main() {
	addr := flag.String("addr", "127.0.0.1:50051", "gRPC server address")
	listingID := flag.String("listing", "L-1001", "listing id")
	copyText := flag.String("copy", "battery waterproof fast charging lightweight", "ad copy")
	flag.Parse()

	conn, err := grpc.NewClient(*addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		log.Fatalf("dial: %v", err)
	}
	defer conn.Close()
	client := pb.NewSchedulerClient(conn)

	resp, err := client.SchedulePipeline(context.Background(), &pb.ScheduleRequest{
		ListingId:       *listingID,
		CopyText:        *copyText,
		ProfileVersion:  "v1",
		CopyVersion:     "c1",
		RubricVersion:   "v1",
		KnowledgeVersion: "s1",
	})
	if err != nil {
		log.Fatalf("schedule: %v", err)
	}
	fmt.Printf("scheduled job: %s (%s)\n", resp.GetJobId(), resp.GetStatus())

	for {
		status, err := client.GetJobStatus(context.Background(), &pb.JobStatusRequest{JobId: resp.GetJobId()})
		if err != nil {
			log.Fatalf("status: %v", err)
		}
		fmt.Printf("job %s: %s (retries=%d)\n", status.GetJobId(), status.GetStatus(), status.GetRetries())
		if status.GetStatus() == "done" || status.GetStatus() == "failed" {
			fmt.Println(status.GetResult())
			break
		}
		time.Sleep(1 * time.Second)
	}
}
