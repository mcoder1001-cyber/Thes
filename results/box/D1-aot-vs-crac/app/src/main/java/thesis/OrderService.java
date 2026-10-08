package thesis;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validator;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * An ordinary Spring service: deserialize JSON, validate, transform, aggregate,
 * serialize back. This is the shape of a real Java FaaS handler, and it drags in
 * Jackson, Hibernate Validator and a lot of Spring machinery -- which is exactly
 * the code that has to be class-loaded and JIT-compiled on a cold start.
 */
@Service
public class OrderService {

    private final ObjectMapper mapper;
    private final Validator validator;

    public OrderService(ObjectMapper mapper, Validator validator) {
        this.mapper = mapper;
        this.validator = validator;
    }

    public String handle(String json) throws Exception {
        Order[] orders = mapper.readValue(json, Order[].class);

        List<Order> valid = new ArrayList<>();
        for (Order o : orders) {
            Set<ConstraintViolation<Order>> v = validator.validate(o);
            if (v.isEmpty()) valid.add(o);
        }

        Map<String, Double> byRegion = valid.stream()
                .collect(Collectors.groupingBy(
                        Order::region,
                        Collectors.summingDouble(o -> o.qty() * o.price())));

        List<Map.Entry<String, Double>> top = byRegion.entrySet().stream()
                .sorted(Map.Entry.<String, Double>comparingByValue(Comparator.reverseOrder()))
                .limit(10)
                .toList();

        return mapper.writeValueAsString(Map.of(
                "accepted", valid.size(),
                "rejected", orders.length - valid.size(),
                "top", top));
    }
}
