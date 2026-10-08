package thesis;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;

public record Order(
        @NotBlank String id,
        @NotBlank String region,
        @Min(1) int qty,
        @Positive double price,
        String note) {
}
